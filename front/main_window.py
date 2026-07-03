"""
메인 윈도우: StartPage -> 시나리오 선택 -> LabelingPage(distraction/drowsiness/cognitive).

출력 구조: <home_dir>/labeled_output/session_{trial_num:03d}_id_{subject_id}/...
draft 임시 파일: <home_dir>/.labeling_drafts/{trial_folder_name}.json
  (원본 raw 데이터 폴더는 절대 건드리지 않음)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from back.models import Scenario
from back.session_loader import SessionLoader
from back.survey_parser import SurveyParser
from back.draft_store import DraftStore
from back.segment_exporter import SegmentExporter
from back.label_taxonomy import load_dms_actions

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget
)

from start_page import StartPage
from labeling_page import LabelingPage

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

    def _build_scenario_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.session_info_label = QLabel("")
        layout.addWidget(self.session_info_label)

        for scenario in Scenario:
            btn = QPushButton(f"{scenario.value} 라벨링 시작")
            btn.clicked.connect(lambda checked=False, s=scenario: self._open_labeling(s))
            layout.addWidget(btn)

        back_btn = QPushButton("세션 다시 선택")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back_btn)

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
            windows = self._task_windows_by_scenario.get(scenario, [])
            page = LabelingPage(
                scenario=scenario, trial=self._trial, task_windows=windows,
                draft_store=self._draft_store, exporter=self._exporter,
                areas=self.areas,
            )
            self._labeling_pages[scenario] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self._labeling_pages[scenario])
