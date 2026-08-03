"""
메인 윈도우: StartPage -> 시나리오 선택 -> LabelingPage(distraction/drowsiness/cognitive).

출력 구조: <home_dir>/labeled_output/session_{trial_num:03d}_id_{subject_id}/...
draft 임시 파일: <home_dir>/.labeling_drafts/{trial_folder_name}.json
  (원본 raw 데이터 폴더는 절대 건드리지 않음)
"""
import re
import sys
from pathlib import Path

from back.models import Scenario
from back.session_loader import SessionLoader
from back.survey_parser import SurveyParser
from back.draft_store import DraftStore
from back.segment_exporter import SegmentExporter
from back.label_taxonomy import load_dms_actions

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QMessageBox,
)

from front.start_page import StartPage
from front.labeling_page import LabelingPage
from front.labeling_page_loader import LabelingPageDataLoader

_TRIAL_NAME_RE = re.compile(r"^id(?P<id>\w+?)_trial(?P<trial>\d+)_")


class MainWindow(QMainWindow):
    def __init__(self, dms_actions_xlsx: str = None):
        super().__init__()
        self.setWindowTitle("DMS Labeling Tool")
        self.resize(1400, 900)

        self.dms_actions_xlsx = dms_actions_xlsx
        self.areas = load_dms_actions(dms_actions_xlsx) if dms_actions_xlsx else []

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.start_page = StartPage()
        self.start_page.session_selected.connect(self._on_session_selected)
        self.stack.addWidget(self.start_page)  # index 0

        self.scenario_page = self._build_scenario_page()
        self.stack.addWidget(self.scenario_page)  # index 1

        self._labeling_pages: dict[Scenario, LabelingPage] = {}
        self._trial = None
        self._task_windows_by_scenario: dict = {}
        self._draft_store: DraftStore | None = None
        self._exporter: SegmentExporter | None = None
        self._audio_cache_dir: Path | None = None

    def closeEvent(self, event):
        """메인 창을 닫으면 열려있는 다른 창(예: StartPage의 디렉토리 선택
        다이얼로그)과 상관없이 앱 전체를 종료한다."""
        QApplication.instance().quit()
        event.accept()

    def _build_scenario_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        back_btn = QPushButton("← 뒤로 (세션 다시 선택)")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back_btn, alignment=Qt.AlignLeft)

        self.session_info_label = QLabel("")
        layout.addWidget(self.session_info_label)

        self._scenario_buttons: list[QPushButton] = []
        for scenario in Scenario:
            btn = QPushButton(f"{scenario.value} 라벨링 시작")
            btn.clicked.connect(lambda checked=False, s=scenario: self._open_labeling(s))
            layout.addWidget(btn)
            self._scenario_buttons.append(btn)

        layout.addStretch()
        return page

    # ------------------------------------------------------------------
    def _on_session_selected(self, home_dir: str, trial_folder_name: str):
        loader = SessionLoader(home_dir)
        self._trial = loader.load_trial(trial_folder_name)

        survey = SurveyParser(str(self._trial.survey_dir))
        parsed = survey.parse_all()
        self._task_windows_by_scenario = {
            Scenario.DISTRACTION: parsed["distraction"],
            Scenario.DROWSINESS: parsed["distraction"],  # drowsiness는 distraction window에 내장됨
            Scenario.COGNITIVE: parsed["cognitive"],
        }

        m = _TRIAL_NAME_RE.match(trial_folder_name)
        subject_id = m.group("id") if m else trial_folder_name
        trial_num = int(m.group("trial")) if m else 0

        home = Path(home_dir)
        session_dir = home / "labeled_output" / f"session_{trial_num:03d}_id_{subject_id}"
        draft_path = home / ".labeling_drafts" / f"{trial_folder_name}.json"
        self._audio_cache_dir = home / ".labeling_drafts" / "audio_cache" / trial_folder_name

        self._draft_store = DraftStore(str(draft_path))
        self._exporter = SegmentExporter(self._trial, session_dir)
        self._labeling_pages = {}  # 세션이 바뀌면 이전 페이지 캐시 폐기

        self.session_info_label.setText(
            f"트라이얼: {trial_folder_name}\n출력 위치: {session_dir}"
        )
        self.stack.setCurrentIndex(1)

    def _open_labeling(self, scenario: Scenario):
        if self._trial is None:
            return
        if scenario not in self._labeling_pages:
            # 카메라 인덱스 생성 + 오디오 스티칭이 무거워서(수 초~수십 초) 그대로
            # LabelingPage 생성자 안에서 하면 화면 전환이 멈춰 OS가 "응답 없음"을
            # 띄우는 문제가 있었다. 그 계산(순수 back/ 로직, Qt 위젯과 무관)만
            # 먼저 백그라운드 스레드에서 끝내고, 끝나면 그 결과로 LabelingPage를
            # 빠르게 조립한다. LabelingPage(QWidget)는 메인 스레드에서만 만들 수
            # 있어서 이 부분만은 백그라운드로 옮길 수 없음.
            for btn in self._scenario_buttons:
                btn.setEnabled(False)
            loader = LabelingPageDataLoader(self._trial, self._audio_cache_dir, parent=self)
            loader.loaded.connect(
                lambda camera_indices, mic_name, audio_result:
                    self._finish_open_labeling(scenario, camera_indices, mic_name, audio_result)
            )
            loader.failed.connect(self._on_labeling_page_load_failed)
            self._pending_loader = loader  # 참조 유지 (없으면 GC로 스레드가 조기 정리될 수 있음)
            loader.start()
            return
        self.stack.setCurrentWidget(self._labeling_pages[scenario])

    def _finish_open_labeling(self, scenario: Scenario, camera_indices: dict,
                               default_mic_name, audio_result):
        for btn in self._scenario_buttons:
            btn.setEnabled(True)
        windows = self._task_windows_by_scenario.get(scenario, [])
        page = LabelingPage(
            scenario=scenario, trial=self._trial, task_windows=windows,
            draft_store=self._draft_store, exporter=self._exporter,
            areas=self.areas, audio_cache_dir=self._audio_cache_dir,
            camera_indices=camera_indices, default_mic_name=default_mic_name, audio_result=audio_result,
        )
        page.back_requested.connect(lambda: self._on_back_from_labeling(page))
        self._labeling_pages[scenario] = page
        self.stack.addWidget(page)
        self._show_page_when_audio_ready(page)

    def _on_labeling_page_load_failed(self, error_message: str):
        for btn in self._scenario_buttons:
            btn.setEnabled(True)
        QMessageBox.critical(self, "오류", f"라벨링 화면을 여는 중 오류가 발생했습니다:\n{error_message}")

    def _show_page_when_audio_ready(self, page: LabelingPage):
        """오디오(스티칭된 wav, 수백 MB일 수 있음) 로딩이 실제로 끝난 뒤에야
        화면을 전환한다 - 로딩 중에 화면부터 넘기면 QMediaPlayer.setPosition()이
        조용히 무시돼서 라벨러가 재생을 누르는 순간 의도한 위치가 아니라 맨
        처음부터 재생되는 문제가 있었다. 기다리는 동안 시나리오 버튼을 잠가서
        중복 클릭으로 페이지가 여러 번 만들어지는 것도 막는다."""
        if page.playback.is_audio_ready:
            self.stack.setCurrentWidget(page)
            return

        for btn in self._scenario_buttons:
            btn.setEnabled(False)

        def _on_ready():
            page.playback.audio_ready.disconnect(_on_ready)
            for btn in self._scenario_buttons:
                btn.setEnabled(True)
            self.stack.setCurrentWidget(page)

        page.playback.audio_ready.connect(_on_ready)

    def _on_back_from_labeling(self, page: LabelingPage):
        """다른 시나리오로 다시 열 때 재사용하려고 페이지를 캐시해두므로,
        뒤로 가기만 하고 재생을 안 멈추면 화면 밖에서 영상/오디오가 계속
        재생된다 - 시나리오 선택으로 돌아갈 땐 반드시 멈춘다."""
        page.playback.pause()
        self.stack.setCurrentIndex(1)
