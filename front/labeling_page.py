"""
시나리오(distraction/drowsiness/cognitive) 공통 라벨링 페이지.

boundaries_locked=True인 시나리오(drowsiness, cognitive)는 TaskWindow에서
계산된 구간을 "가이드라인"으로 자동 채워줍니다 - 하지만 어디까지나 기본값일
뿐, 라벨러가 "시작점 지정"/"끝점 지정" 버튼(+ 프레임 단위 이동)으로 언제든
덮어써서 더 정밀하게 조정할 수 있습니다. "가이드라인 구간으로 리셋" 버튼으로
자동 계산값으로 되돌릴 수 있습니다.
boundaries_locked=False인 시나리오(distraction)는 애초에 자동 채움 없이,
라벨러가 재생하면서 직접 구간을 잘라 여러 개(복합 동작을 여러 서브구간으로
나누는 경우 등) 만듭니다.
"""
import sys
from pathlib import Path

import cv2

from back.models import Scenario, TaskWindow, DistractionTaskWindow, CognitiveTaskWindow, LabelDraft
from back.session_loader import TrialData
from back.timestamp_index import CameraTimestampIndex
from back.draft_store import DraftStore
from back.segment_exporter import SegmentExporter
from back.label_taxonomy import AreaTaxonomy
from back.audio_stitcher import build_continuous_audio

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QListWidget, QListWidgetItem, QScrollBar
)

from front.widgets.timeline_widget import TimelineWidget, TimelineMarker
from front.widgets.video_panel import VideoPanel
from front.widgets.label_forms import DistractionLabelForm, DrowsinessLabelForm, CognitiveLabelForm
from front.stream_player import StreamPlayer
from front.playback_controller import PlaybackController
from front.export_worker import ExportWorker

# UI에 표시할 카메라 조합 (PDF 기준: RGB + IR, depth는 화면엔 안 띄우고 백엔드에서만 저장)
DISPLAY_STREAMS = [
    ("driver", "rgb", "Driver RGB"), ("behavior", "rgb", "Behavior RGB"), ("road", "rgb", "Road RGB"),
    ("driver", "infrared", "Driver IR"), ("behavior", "infrared", "Behavior IR"), ("road", "infrared", "Road IR"),
]

MARKER_COLORS = {
    Scenario.DISTRACTION: "#4a90d9",
    Scenario.DROWSINESS: "#d9954a",
    Scenario.COGNITIVE: "#7a4ad9",
}


class LabelingPage(QWidget):
    back_requested = Signal()

    _SCROLLBAR_RESOLUTION = 10000  # 타임라인 스크롤바 내부 해상도 (total_start~total_end를 이 정수 범위로 매핑)

    def __init__(self, scenario: Scenario, trial: TrialData, task_windows: list[TaskWindow],
                 draft_store: DraftStore, exporter: SegmentExporter,
                 areas: list[AreaTaxonomy], audio_cache_dir: Path,
                 camera_indices: dict, default_mic_name: str | None, audio_result, parent=None):
        """camera_indices/default_mic_name/audio_result: front/labeling_page_loader.py의
        LabelingPageDataLoader가 백그라운드 스레드에서 미리 계산해둔 값. 카메라
        timestamp csv 파싱과 오디오 세그먼트 이어붙이기가 무거워서(수 초~수십 초),
        생성자 안에서 직접 계산하면 화면 전환이 멈춰 OS가 "응답 없음"을 띄우는
        문제가 있었음 - 그래서 이 생성자는 이미 계산된 값만 받아 빠르게 조립만 한다."""
        super().__init__(parent)
        self.scenario = scenario
        self.trial = trial
        self.task_windows = task_windows
        self.draft_store = draft_store
        self.exporter = exporter
        self.areas = areas
        self.audio_cache_dir = audio_cache_dir
        self.boundaries_locked = scenario in (Scenario.DROWSINESS, Scenario.COGNITIVE)

        self.current_window: TaskWindow | None = None
        self.pending_start: float | None = None
        self.pending_end: float | None = None
        self._syncing_scrollbar = False  # 타임라인->스크롤바 동기화 중 재귀 신호 방지

        self.camera_indices: dict = camera_indices
        self._compute_total_range()
        self._build_ui(default_mic_name=default_mic_name)
        self._build_playback(precomputed_audio_result=audio_result)

        if self.task_windows:
            self._load_task_window(self.task_windows[0])
        self._refresh_progress_label()

        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    def eventFilter(self, obj, event):
        """자식 위젯(버튼/콤보박스 등)이 포커스를 가진 상태에서도 스페이스바는
        항상 재생/일시정지 토글로만 동작하게 가로챈다 (그 위젯의 기본 스페이스바
        동작 - 예: 버튼 재클릭 - 이 먼저 실행되는 걸 막음). 다른 키는 그대로 통과."""
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space:
            self._toggle_play_pause()
            return True
        return super().eventFilter(obj, event)

    def _toggle_play_pause(self):
        if self.playback.is_playing:
            self.playback.pause()
        else:
            self.playback.play()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._toggle_play_pause()
        elif event.key() == Qt.Key_Left:
            if event.modifiers() & Qt.ShiftModifier:
                self._step_frame(-1)
            else:
                self.playback.seek_to(self.timeline.playhead_ts - 1.0)
        elif event.key() == Qt.Key_Right:
            if event.modifiers() & Qt.ShiftModifier:
                self._step_frame(1)
            else:
                self.playback.seek_to(self.timeline.playhead_ts + 1.0)
        else:
            super().keyPressEvent(event)

    def _step_frame(self, direction: int):
        """Shift+←/→ 또는 프레임 이동 버튼: 정지 상태에서 정확히 프레임 하나씩 이동."""
        if self.playback.is_playing:
            self.playback.pause()
        self.playback.set_playback_limit(None)  # 구간 미리보기 한계 해제 - 직접 프레임을 옮기는 건 자유 탐색으로 봄
        self.playback.seek_to(self.timeline.playhead_ts + direction * self.frame_step_sec)

    # ------------------------------------------------------------------
    def _compute_total_range(self):
        """self.camera_indices(생성자에서 미리 계산되어 전달됨)로부터 타임라인
        전체 범위만 빠르게 계산 - 카메라 인덱스 자체를 새로 만들진 않는다."""
        all_starts, all_ends = [], []
        for idx in self.camera_indices.values():
            if idx.first_t_sec is not None:
                all_starts.append(idx.first_t_sec)
                all_ends.append(idx.last_t_sec)

        # task window(survey json 기준) 시각도 전체 범위에 합침 - 카메라 녹화 시작/종료가
        # survey 타임스탬프와 살짝 어긋나도(센서 시작 지연 등) 마커가 항상 타임라인 안에
        # 들어오도록 보장 (PDF 요구사항: "시간 축은 전체 영상 처음부터 끝까지 모두 포함")
        for w in self.task_windows:
            all_starts.append(w.start_ts)
            all_ends.append(w.end_ts)

        self.total_start = min(all_starts) if all_starts else 0.0
        self.total_end = max(all_ends) if all_ends else 1.0
        self.frame_step_sec = self._probe_frame_step()

    def _probe_frame_step(self) -> float:
        """프레임 단위 이동(Shift+←/→) 간격. 카메라 세그먼트 하나에서 실제 fps를 읽어옴."""
        for idx in self.camera_indices.values():
            if idx.segment_files:
                cap = cv2.VideoCapture(str(idx.segment_files[0][1]))
                fps = cap.get(cv2.CAP_PROP_FPS)
                cap.release()
                if fps and fps > 0:
                    return 1.0 / fps
        return 1.0 / 30.0

    # ------------------------------------------------------------------
    def _build_ui(self, default_mic_name: str | None = None):
        outer = QHBoxLayout(self)

        left = QVBoxLayout()

        back_btn = QPushButton("← 뒤로 (시나리오 선택)")
        back_btn.clicked.connect(self.back_requested.emit)
        left.addWidget(back_btn, alignment=Qt.AlignLeft)

        self.timeline = TimelineWidget()
        self.timeline.set_range(self.total_start, self.total_end)
        self.timeline.position_clicked.connect(self._on_timeline_clicked)
        left.addWidget(self.timeline)

        zoom_row = QHBoxLayout()
        reset_zoom_btn = QPushButton("전체 보기")
        reset_zoom_btn.clicked.connect(self.timeline.reset_view)
        zoom_row.addWidget(reset_zoom_btn)
        pan_left_btn = QPushButton("◀ 이동")
        pan_right_btn = QPushButton("이동 ▶")
        pan_left_btn.clicked.connect(lambda: self.timeline.pan_by(-0.25))
        pan_right_btn.clicked.connect(lambda: self.timeline.pan_by(0.25))
        zoom_row.addWidget(pan_left_btn)
        zoom_row.addWidget(pan_right_btn)
        zoom_hint = QLabel("휠: 확대/축소 · 우클릭 드래그: 이동")
        zoom_hint.setStyleSheet("color: #888;")
        zoom_row.addWidget(zoom_hint)
        zoom_row.addStretch()
        left.addLayout(zoom_row)

        # 확대된 상태에서 playhead/재생 화면과 별개로 타임라인 위치를 직접 옮길 수 있는 바.
        # TimelineWidget의 view_range_changed와 서로 동기화 (재귀 방지는 _syncing_scrollbar 플래그).
        self.timeline_scrollbar = QScrollBar(Qt.Horizontal)
        self.timeline_scrollbar.valueChanged.connect(self._on_scrollbar_changed)
        self.timeline.view_range_changed.connect(self._on_timeline_view_changed)
        left.addWidget(self.timeline_scrollbar)
        self._on_timeline_view_changed(self.timeline.view_start, self.timeline.view_end)

        grid = QGridLayout()
        self.video_panels: dict[str, VideoPanel] = {}
        for i, (position, modality, title) in enumerate(DISPLAY_STREAMS):
            panel = VideoPanel(title)
            panel.clicked.connect(self._on_video_panel_clicked)
            self.video_panels[f"{position}_{modality}"] = panel
            grid.addWidget(panel, i // 3, i % 3)
        grid_widget = QWidget()
        grid_widget.setLayout(grid)
        left.addWidget(grid_widget, stretch=1)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("재생")
        self.pause_btn = QPushButton("일시정지")
        self.stop_btn = QPushButton("정지")
        self.prev_frame_btn = QPushButton("◀ 프레임")
        self.next_frame_btn = QPushButton("프레임 ▶")
        for btn in (self.prev_frame_btn, self.next_frame_btn):
            btn.setAutoRepeat(True)
            btn.setAutoRepeatDelay(300)     # 누르고 있다가 이 시간(ms) 지나면 반복 시작
            btn.setAutoRepeatInterval(60)   # 이후 반복 간격(ms)
        self.prev_frame_btn.clicked.connect(lambda: self._step_frame(-1))
        self.next_frame_btn.clicked.connect(lambda: self._step_frame(1))
        transport.addWidget(self.play_btn)
        transport.addWidget(self.pause_btn)
        transport.addWidget(self.stop_btn)
        transport.addWidget(self.prev_frame_btn)
        transport.addWidget(self.next_frame_btn)

        transport.addWidget(QLabel("오디오:"))
        self.audio_combo = QComboBox()
        self.audio_combo.addItems([
            mic_name for mic_name, stream in self.trial.audio.items() if stream.segment_files
        ])
        # 기본 재생 마이크는 로더(LabelingPageDataLoader)가 미리 고른 것과 반드시
        # 같아야 한다 - 그래야 콤보박스 표시와 실제로 로드된 오디오가 일치함.
        # currentTextChanged 연결 전에 설정해야 self.playback이 아직 없는 이
        # 시점에 _on_audio_stream_changed가 안 불림.
        if default_mic_name is not None and self.audio_combo.findText(default_mic_name) >= 0:
            self.audio_combo.setCurrentText(default_mic_name)
        self.audio_combo.setEnabled(self.audio_combo.count() > 0)
        self.audio_combo.currentTextChanged.connect(self._on_audio_stream_changed)
        transport.addWidget(self.audio_combo)

        transport.addWidget(QLabel("배속:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.25x", "0.5x", "0.75x", "1.0x", "1.5x", "2.0x"])
        # audio_combo와 동일한 이유로, 기본값은 currentTextChanged 연결 전에 설정
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.currentTextChanged.connect(self._on_speed_changed)
        transport.addWidget(self.speed_combo)

        left.addLayout(transport)

        outer.addLayout(left, stretch=3)

        # ---- 우측 사이드 패널 ----
        side = QVBoxLayout()
        side.addWidget(QLabel(f"<b>태스크: {self.scenario.value}</b>"))

        self.no_data_banner = QLabel()
        self.no_data_banner.setWordWrap(True)
        self.no_data_banner.setStyleSheet(
            "color: #b00020; font-weight: bold; padding: 4px; "
            "background-color: #fdecea; border-radius: 4px;"
        )
        self.no_data_banner.setVisible(False)
        side.addWidget(self.no_data_banner)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #555;")
        side.addWidget(self.progress_label)

        self.coverage_warning_label = QLabel()
        self.coverage_warning_label.setWordWrap(True)
        self.coverage_warning_label.setStyleSheet("color: #b06000; font-weight: bold;")
        self.coverage_warning_label.setVisible(False)
        side.addWidget(self.coverage_warning_label)

        side.addWidget(QLabel("불러오기"))
        self.window_combo = QComboBox()
        self.window_combo.addItems([w.window_id for w in self.task_windows])
        # currentIndexChanged는 선택값이 실제로 바뀔 때만 발생해서, 이미 선택된
        # 항목을 다시 고르면 아무 반응이 없었음(예: task1->task2->task1은 되는데
        # task1이 이미 선택된 상태에서 task1을 다시 고르면 안 됨). activated는
        # 사용자가 드롭다운에서 항목을 고르는 행위 자체에 반응해서 같은 항목을
        # 다시 골라도 항상 발생한다.
        self.window_combo.activated.connect(self._on_window_selected)
        side.addWidget(self.window_combo)

        self.label_form = self._make_label_form()
        side.addWidget(self.label_form)

        if self.boundaries_locked:
            guideline_hint = QLabel("자동 계산된 가이드라인 구간이 채워져 있습니다. 필요하면 아래 버튼으로 정밀하게 조정하세요.")
            guideline_hint.setWordWrap(True)
            guideline_hint.setStyleSheet("color: #888;")
            side.addWidget(guideline_hint)

        mark_row = QHBoxLayout()
        self.mark_start_btn = QPushButton("시작점 지정")
        self.mark_end_btn = QPushButton("끝점 지정")
        self.mark_start_btn.clicked.connect(self._on_mark_start)
        self.mark_end_btn.clicked.connect(self._on_mark_end)
        mark_row.addWidget(self.mark_start_btn)
        mark_row.addWidget(self.mark_end_btn)
        side.addLayout(mark_row)

        self.reset_guideline_btn = QPushButton("가이드라인 구간으로 리셋")
        self.reset_guideline_btn.clicked.connect(self._on_reset_to_guideline)
        side.addWidget(self.reset_guideline_btn)

        self.save_draft_btn = QPushButton("이 구간 저장 (작업중에 추가)")
        self.save_draft_btn.clicked.connect(self._on_save_draft)
        side.addWidget(self.save_draft_btn)

        if not self.task_windows:
            self.no_data_banner.setText(
                "이 트라이얼에는 이 시나리오에 해당하는 데이터가 없습니다 "
                "(survey json에 해당 섹션이 없거나 비어 있음)."
            )
            self.no_data_banner.setVisible(True)
            self.window_combo.setEnabled(False)
            self.save_draft_btn.setEnabled(False)
            self.mark_start_btn.setEnabled(False)
            self.mark_end_btn.setEnabled(False)
            self.reset_guideline_btn.setEnabled(False)

        side.addWidget(QLabel("작업 중인 구간들"))
        self.draft_list = QListWidget()
        self.draft_list.itemClicked.connect(self._on_draft_item_clicked)
        side.addWidget(self.draft_list)

        draft_actions = QHBoxLayout()
        self.edit_draft_btn = QPushButton("선택 구간 수정")
        self.delete_draft_btn = QPushButton("선택 구간 삭제")
        self.edit_draft_btn.clicked.connect(self._on_edit_draft)
        self.delete_draft_btn.clicked.connect(self._on_delete_draft)
        draft_actions.addWidget(self.edit_draft_btn)
        draft_actions.addWidget(self.delete_draft_btn)
        side.addLayout(draft_actions)

        self.final_commit_btn = QPushButton("최종 저장 (모두 커밋)")
        self.final_commit_btn.setStyleSheet("background-color: #2ecc71; font-weight: bold;")
        self.final_commit_btn.clicked.connect(self._on_final_commit)
        side.addWidget(self.final_commit_btn)

        side.addStretch()
        outer.addLayout(side, stretch=2)

        self.play_btn.clicked.connect(lambda: self.playback.play())
        self.pause_btn.clicked.connect(lambda: self.playback.pause())
        self.stop_btn.clicked.connect(lambda: self.playback.stop())

        # 버튼/콤보박스/리스트 등 자식 위젯이 포커스를 가진 상태에서 스페이스바를
        # 누르면 Qt 기본 동작(그 위젯을 다시 클릭/토글)이 먼저 먹어버려서 재생/일시정지
        # 토글이 안 먹힘 - 모든 자식에 이벤트 필터를 걸어 스페이스바만은 항상 이
        # 페이지가 먼저 가로채게 한다 (정지 버튼 등 다른 동작은 그대로 각자 처리).
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def _make_label_form(self) -> QWidget:
        if self.scenario == Scenario.DISTRACTION:
            return DistractionLabelForm(self.areas)
        elif self.scenario == Scenario.DROWSINESS:
            return DrowsinessLabelForm()
        else:
            return CognitiveLabelForm()

    # ------------------------------------------------------------------
    def _build_playback(self, precomputed_audio_result=None):
        self.playback = PlaybackController(self.total_start, self.total_end, parent=self)
        self.playback.time_changed.connect(self.timeline.set_playhead)

        for position, modality, _title in DISPLAY_STREAMS:
            key = f"{position}_{modality}"
            idx = self.camera_indices.get((position, modality))
            panel = self.video_panels[key]
            if idx is None:
                panel.set_unavailable()
                continue
            # road 카메라는 광축 기준 180도 돌아간 채 장착되어 있어서 화면 표시 전에 보정
            player = StreamPlayer(idx, flip_180=(position == "road"))
            self.playback.register_stream(key, player, panel.update_frame)

        # 오디오 스티칭은 이미 LabelingPageDataLoader가 백그라운드에서 끝내고
        # 넘겨준 결과를 그대로 쓴다 (_load_selected_audio()는 마이크를 나중에
        # 콤보박스에서 직접 바꿀 때만 다시 호출됨).
        if precomputed_audio_result is not None:
            wav_path, base_ts = precomputed_audio_result
            self.playback.set_audio(wav_path, base_ts)
        self.playback.seek_to(self.total_start)

    def _select_audio_stream(self):
        """오디오는 마이크 하나만 마스터 시계로 쓰면 되므로, 콤보박스(audio_combo)에서
        라벨러가 고른 마이크를 쓴다. wav 세그먼트가 없는 마이크(예: timestamp csv만
        있는 마이크)는 콤보박스에 애초에 안 올라가 있음."""
        mic_name = self.audio_combo.currentText()
        return self.trial.audio.get(mic_name)

    def _load_selected_audio(self):
        """audio_combo에서 선택된 마이크로 재생용 오디오를 (다시) 빌드한다."""
        mic = self._select_audio_stream()
        if mic is None:
            return
        reference_starts = self._reference_segment_starts(len(mic.segment_files))
        result = build_continuous_audio(mic, self.audio_cache_dir,
                                         reference_segment_starts=reference_starts)
        if result is not None:
            wav_path, base_ts = result
            self.playback.set_audio(wav_path, base_ts)

    def _on_audio_stream_changed(self, _mic_name: str):
        """라벨러가 오디오 콤보박스에서 다른 마이크를 고르면 재생 오디오를 교체."""
        was_playing = self.playback.is_playing
        if was_playing:
            self.playback.pause()
        self._load_selected_audio()
        self.playback.seek_to(self.timeline.playhead_ts)
        if was_playing:
            self.playback.play()

    def _on_speed_changed(self, text: str):
        rate = float(text.rstrip("x"))
        self.playback.set_playback_rate(rate)

    def _reference_segment_starts(self, expected_count: int) -> list[float] | None:
        """비디오(카메라) 쪽에서 계산된 세그먼트 시작 시각을 오디오 등 다른 센서의
        기준으로 삼는다 - 카메라는 프레임마다 실측 timestamp가 촘촘해서 세그먼트가
        일부만 담겨있어도 어느 세그먼트인지 훨씬 신뢰도 높게 판단할 수 있다.

        카메라마다 자체 fps 미세 오차가 있어서(실측해보니 세그먼트 하나 없는
        구간을 역산할 때 카메라 간 1~2초 정도 편차 발생) 어떤 스트림을 기준으로
        쓰는지 매번 달라지면 안 되므로, DISPLAY_STREAMS 순서(driver_rgb 우선)로
        고정해서 항상 같은 스트림을 기준으로 삼는다."""
        for position, modality, _title in DISPLAY_STREAMS:
            idx = self.camera_indices.get((position, modality))
            if idx is None:
                continue
            starts = idx.segment_starts
            if starts and len(starts) == expected_count:
                return starts
        return None

    # ------------------------------------------------------------------
    def _on_timeline_clicked(self, ts: float):
        # 구간 미리보기(_on_draft_item_clicked)로 걸어둔 재생 한계가 있으면
        # 해제 - 타임라인을 직접 클릭한 건 자유롭게 재생하고 싶다는 뜻으로 본다.
        self.playback.set_playback_limit(None)
        self.playback.seek_to(ts)

    def _on_video_panel_clicked(self):
        # 영상 화면을 클릭하는 것도 "자유롭게 다루고 싶다"는 뜻으로 보고 구간
        # 미리보기 한계를 해제 (위치 자체는 안 건드림 - 포커스만 받으려고
        # 클릭하는 경우도 많아서 재생 위치를 옮기진 않는다).
        self.playback.set_playback_limit(None)

    def _on_timeline_view_changed(self, view_start: float, view_end: float):
        """TimelineWidget이 보이는 범위가 바뀌면(휠 확대/축소, 우클릭 드래그, 이동
        버튼, playhead 자동 추적 등 - 원인 무관) 스크롤바 위치/두께를 그 범위에
        맞춰준다. _on_scrollbar_changed로 다시 되돌아 트리거되지 않게 플래그로 막음."""
        total_span = self.timeline.total_end - self.timeline.total_start
        if total_span <= 0:
            return
        res = self._SCROLLBAR_RESOLUTION
        page = max(1, int(round((view_end - view_start) / total_span * res)))
        value = int(round((view_start - self.timeline.total_start) / total_span * res))

        self._syncing_scrollbar = True
        self.timeline_scrollbar.setRange(0, max(0, res - page))
        self.timeline_scrollbar.setPageStep(page)
        self.timeline_scrollbar.setValue(value)
        self._syncing_scrollbar = False

    def _on_scrollbar_changed(self, value: int):
        """라벨러가 스크롤바를 직접 드래그/클릭했을 때만 타임라인 뷰를 이동시킨다
        (타임라인 쪽 변화로 스크롤바가 맞춰지는 중일 땐 _syncing_scrollbar로 무시)."""
        if self._syncing_scrollbar:
            return
        total_span = self.timeline.total_end - self.timeline.total_start
        if total_span <= 0:
            return
        span = self.timeline.view_end - self.timeline.view_start
        new_start = self.timeline.total_start + value / self._SCROLLBAR_RESOLUTION * total_span
        self.timeline.set_view_range(new_start, new_start + span)

    def _on_window_selected(self, idx: int):
        if 0 <= idx < len(self.task_windows):
            self._load_task_window(self.task_windows[idx])

    def _compute_guideline(self, window: TaskWindow) -> tuple[float, float] | None:
        """이 window에 대해 자동 계산되는 가이드라인 구간 (survey 기반 기본값).
        어디까지나 시작값일 뿐이고, 라벨러가 시작점/끝점 버튼으로 덮어쓸 수 있음."""
        if self.scenario == Scenario.DROWSINESS and isinstance(window, DistractionTaskWindow):
            start_dt, end_dt = window.drowsiness_window
            return start_dt.timestamp(), end_dt.timestamp()
        elif self.scenario == Scenario.COGNITIVE and isinstance(window, CognitiveTaskWindow):
            return window.start_ts, window.end_ts
        return None

    def _load_task_window(self, window: TaskWindow):
        self.current_window = window
        self.pending_start, self.pending_end = None, None
        self.timeline.set_pending_selection(None, None)
        self.playback.set_playback_limit(None)  # 다른 태스크로 넘어가면 구간 미리보기 한계 해제

        markers = [TimelineMarker(w.window_id, w.start_ts, w.end_ts, MARKER_COLORS[self.scenario])
                   for w in self.task_windows]
        self.timeline.set_task_markers(markers)
        self._refresh_draft_markers()

        if self.scenario == Scenario.DROWSINESS and isinstance(window, DistractionTaskWindow):
            self.label_form.set_prefill_kss(window.kss_score)
        elif self.scenario == Scenario.COGNITIVE and isinstance(window, CognitiveTaskWindow):
            self.label_form.set_prefill(window.task_name, window.difficulty)
        elif isinstance(window, DistractionTaskWindow):
            self.label_form.set_hint(window.distraction_task_text)

        guideline = self._compute_guideline(window)
        if guideline is not None:
            self.pending_start, self.pending_end = guideline
            self.timeline.set_pending_selection(self.pending_start, self.pending_end)
            self.timeline.zoom_to_fit(self.pending_start, self.pending_end)
            self.playback.seek_to(self.pending_start)
        else:
            self.timeline.zoom_to_fit(window.start_ts, window.end_ts)
            self.playback.seek_to(window.start_ts)

        check_start = self.pending_start if self.pending_start is not None else window.start_ts
        check_end = self.pending_end if self.pending_end is not None else window.end_ts
        if self._window_has_camera_coverage(check_start, check_end):
            self.coverage_warning_label.setVisible(False)
        else:
            self.coverage_warning_label.setText(
                "⚠ 이 구간에 해당하는 카메라/오디오 녹화 데이터가 없습니다 "
                "(survey 시각과 실제 녹화 구간이 다르거나 파일이 누락됨)."
            )
            self.coverage_warning_label.setVisible(True)

        self._refresh_draft_list()

    def _window_has_camera_coverage(self, start_ts: float, end_ts: float) -> bool:
        """대략적인 체크: 이 구간이 어느 카메라 스트림의 녹화 범위와 조금이라도 겹치는지.
        (스트림 내부에 gap이 있는 경우까지는 못 잡지만, 오늘 겪은 것처럼 아예 다른
        세션 시간대를 가리키는 survey 데이터를 걸러내는 용도로는 충분함)"""
        for idx in self.camera_indices.values():
            if idx.first_t_sec is None:
                continue
            if idx.first_t_sec <= end_ts and start_ts <= idx.last_t_sec:
                return True
        return False

    def _refresh_progress_label(self):
        total = len(self.task_windows)
        if total == 0:
            self.progress_label.setText("")
            return
        completed_ids = self.draft_store.committed_window_ids(self.scenario)
        completed = sum(1 for w in self.task_windows if w.window_id in completed_ids)
        self.progress_label.setText(f"진행 상황: {completed} / {total} 완료")
        for i, w in enumerate(self.task_windows):
            mark = "✓ " if w.window_id in completed_ids else ""
            self.window_combo.setItemText(i, f"{mark}{w.window_id}")

    # ------------------------------------------------------------------
    def _on_mark_start(self):
        self.playback.set_playback_limit(None)  # 새 구간을 정의하기 시작하는 행위 - 구간 미리보기 한계 해제
        self.pending_start = self._current_playhead_ts()
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)

    def _on_mark_end(self):
        self.playback.set_playback_limit(None)
        self.pending_end = self._current_playhead_ts()
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)

    def _on_reset_to_guideline(self):
        """자동 계산값(또는 distraction은 instruction 전체 구간)으로 되돌림."""
        if self.current_window is None:
            return
        self.playback.set_playback_limit(None)
        guideline = self._compute_guideline(self.current_window)
        if guideline is None:
            guideline = (self.current_window.start_ts, self.current_window.end_ts)
        self.pending_start, self.pending_end = guideline
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)
        self.timeline.zoom_to_fit(self.pending_start, self.pending_end)
        self.playback.seek_to(self.pending_start)

    def _current_playhead_ts(self) -> float:
        return self.timeline.playhead_ts

    # ------------------------------------------------------------------
    def _on_save_draft(self):
        if self.pending_start is None or self.pending_end is None or self.pending_start >= self.pending_end:
            QMessageBox.warning(self, "구간 필요", "시작점과 끝점을 먼저 지정해주세요.")
            return

        overlap = self.draft_store.find_overlap(self.scenario, self.pending_start, self.pending_end)
        if overlap is not None:
            QMessageBox.warning(
                self, "구간 겹침",
                f"이미 저장된 구간과 시간이 겹칩니다 ({overlap.start_ts:.2f} ~ {overlap.end_ts:.2f}).\n"
                "겹치는 구간을 먼저 수정하거나 삭제한 뒤 다시 저장해주세요.",
            )
            return

        fields, overrides = self.label_form.get_label_fields()
        draft = self.draft_store.add_draft(
            scenario=self.scenario,
            start_ts=self.pending_start, end_ts=self.pending_end,
            source_window_id=self.current_window.window_id if self.current_window else None,
            label_fields=fields,
        )
        draft.is_free_text_override = overrides
        self.draft_store.save()

        if not self.boundaries_locked:
            self.pending_start, self.pending_end = None, None
            self.timeline.set_pending_selection(None, None)

        self._refresh_draft_markers()
        self._refresh_draft_list()

    def _selected_draft_id(self) -> str | None:
        item = self.draft_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_draft_item_clicked(self, item: QListWidgetItem):
        """목록에서 구간을 클릭하면 (수정/삭제와 별개로) 그 구간으로 재생 위치를
        옮기고 타임라인을 그 범위에 맞게 확대 - 완료된 구간도 내용을 미리 볼 수
        있게 함(수정/삭제는 여전히 불가). 재생을 누르면 그 구간 끝에서 자동으로
        멈춰서, 이어지는 다른 구간까지 그냥 쭉 재생되지 않게 한다."""
        draft_id = item.data(Qt.UserRole)
        draft = self.draft_store.drafts.get(draft_id)
        if draft is None:
            return
        self.timeline.zoom_to_fit(draft.start_ts, draft.end_ts)
        self.playback.set_playback_limit(draft.end_ts)
        self.playback.seek_to(draft.start_ts)

    def _on_delete_draft(self):
        draft_id = self._selected_draft_id()
        if draft_id is None:
            QMessageBox.information(self, "선택 필요", "삭제할 구간을 목록에서 먼저 선택해주세요.")
            return
        draft = self.draft_store.drafts.get(draft_id)
        if draft is not None and draft.committed:
            QMessageBox.information(self, "삭제 불가", "이미 최종 저장된 구간은 삭제할 수 없습니다.")
            return
        self.draft_store.remove_draft(draft_id)
        self._refresh_draft_markers()
        self._refresh_draft_list()

    def _on_edit_draft(self):
        draft_id = self._selected_draft_id()
        if draft_id is None:
            QMessageBox.information(self, "선택 필요", "수정할 구간을 목록에서 먼저 선택해주세요.")
            return
        draft = self.draft_store.drafts.get(draft_id)
        if draft is None:
            return
        if draft.committed:
            QMessageBox.information(self, "수정 불가", "이미 최종 저장된 구간은 수정할 수 없습니다.")
            return

        self.pending_start, self.pending_end = draft.start_ts, draft.end_ts
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)
        self.label_form.load_values(draft.label_fields, draft.is_free_text_override)
        self.playback.seek_to(self.pending_start)

        # 수정은 "불러와서 폼에 채운 뒤 다시 저장"으로 처리 - 기존 것은 지우고
        # 라벨러가 값을 고쳐서 "이 구간 저장"을 다시 누르면 새 draft로 대체됨.
        self.draft_store.remove_draft(draft_id)
        self._refresh_draft_markers()
        self._refresh_draft_list()

    def _refresh_draft_markers(self):
        drafts = self.draft_store.drafts_for_scenario(self.scenario)
        markers = [TimelineMarker(f"draft:{d.draft_id}", d.start_ts, d.end_ts, "#d0021b")
                   for d in drafts]
        self.timeline.set_draft_markers(markers)

    def _refresh_draft_list(self):
        """확정 전 draft뿐 아니라 이미 최종 저장된 것까지 이 태스크 창에 대해
        전부 보여준다 - "최종 저장"을 눌러도 직전까지 작업한 이력이 목록에서
        사라지지 않고, 이전에 뭘 했는지 계속 볼 수 있게 하기 위함. 완료된 항목은
        "[완료]"로 표시하고 수정/삭제는 막는다(_on_edit_draft/_on_delete_draft)."""
        self.draft_list.clear()
        if self.current_window is None:
            return
        drafts = [d for d in self.draft_store.all_drafts_for_scenario(self.scenario)
                  if d.source_window_id == self.current_window.window_id]
        for i, d in enumerate(drafts, start=1):
            prefix = "[완료] " if d.committed else ""
            item = QListWidgetItem(f"{prefix}Seg{i}  [{d.start_ts:.2f} ~ {d.end_ts:.2f}]  {d.label_fields}")
            item.setData(Qt.UserRole, d.draft_id)
            self.draft_list.addItem(item)

    # ------------------------------------------------------------------
    def _on_final_commit(self):
        drafts = self.draft_store.drafts_for_scenario(self.scenario)
        if not drafts:
            QMessageBox.information(self, "없음", "저장할 구간이 없습니다.")
            return

        reply = QMessageBox.question(
            self, "최종 저장 확인",
            f"{len(drafts)}개 구간을 최종 저장합니다. 저장 후에는 수정할 수 없습니다. 계속할까요?"
        )
        if reply != QMessageBox.Yes:
            return

        jobs = []
        for d in drafts:
            window = next((w for w in self.task_windows if w.window_id == d.source_window_id), None)
            cognitive_task_name = window.task_name if isinstance(window, CognitiveTaskWindow) else None
            jobs.append((d, cognitive_task_name, window))

        self._set_draft_controls_enabled(False)
        self._export_done = 0
        self._export_total = len(jobs)
        self._export_step = ""
        self._update_export_status_text()

        # self.exporter는 distraction/drowsiness/cognitive 세 페이지가 전부 공유
        # (front/main_window.py) - 그걸 그대로 백그라운드 스레드에 넘기면, 다른
        # 시나리오에서 동시에 "최종 저장"을 눌렀을 때 같은 인스턴스의 캐시/카운터를
        # 두 스레드가 동시에 건드리는 경쟁 상태가 생길 수 있다. 그래서 커밋
        # 배치마다 독립된 SegmentExporter를 새로 만든다 - SegmentNamer가 폴더를
        # 스캔해서 번호를 이어가므로(back/segment_exporter.py) 매번 새로 만들어도
        # 번호가 꼬이지 않는다.
        export_instance = SegmentExporter(self.trial, self.exporter.session_dir)

        # self에 보관해서 스레드 객체가 조기에 GC되는 걸 방지 (참조가 없어지면
        # 실행 중이어도 파이썬이 수거할 수 있음)
        self._export_worker = ExportWorker(export_instance, jobs, parent=self)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.step_progress.connect(self._on_export_step_progress)
        self._export_worker.finished_ok.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.start()

    def _update_export_status_text(self):
        self.final_commit_btn.setText(
            f"저장 중... ({self._export_done}/{self._export_total}구간) {self._export_step}"
        )

    def _on_export_progress(self, done: int, total: int):
        self._export_done = done
        self._export_total = total
        self._export_step = ""
        self._update_export_status_text()

    def _on_export_step_progress(self, message: str):
        self._export_step = message
        self._update_export_status_text()

    def _on_export_finished(self, committed: list, export_warnings: list):
        for draft_id, segment_dir in committed:
            self.draft_store.mark_committed(draft_id, segment_dir=segment_dir)
        self._finish_export_ui(export_warnings)

    def _on_export_failed(self, committed: list, error_message: str):
        # 실패 전까지 실제로 export가 끝난 구간은 그대로 커밋 처리 (다시 시도할 때
        # 중복 작업하지 않도록)
        for draft_id, segment_dir in committed:
            self.draft_store.mark_committed(draft_id, segment_dir=segment_dir)
        self._finish_export_ui([], error_message=error_message)

    def _finish_export_ui(self, export_warnings: list, error_message: str = None):
        self._set_draft_controls_enabled(True)
        self.final_commit_btn.setText("최종 저장 (모두 커밋)")
        self._refresh_draft_markers()
        self._refresh_draft_list()
        self._refresh_progress_label()

        if error_message:
            QMessageBox.critical(self, "오류", f"저장 중 오류가 발생했습니다:\n{error_message}")
        elif export_warnings:
            QMessageBox.warning(
                self, "완료 (일부 느린 경로 사용됨)",
                "최종 저장은 완료됐지만, 일부 구간에서 빠른 프레임 탐색이 실패해 "
                "느린 방식으로 대체됐습니다 (정확도에는 영향 없음):\n\n"
                + "\n".join(export_warnings)
            )
        else:
            QMessageBox.information(self, "완료", "최종 저장이 완료되었습니다.")

    def _set_draft_controls_enabled(self, enabled: bool):
        """export가 백그라운드에서 도는 동안 draft_store/exporter를 동시에 건드릴
        수 있는 조작(구간 저장/수정/삭제, 시작·끝점 지정, 다른 태스크로 전환)을
        잠근다."""
        for w in (self.final_commit_btn, self.save_draft_btn, self.edit_draft_btn,
                  self.delete_draft_btn, self.mark_start_btn, self.mark_end_btn,
                  self.reset_guideline_btn, self.window_combo):
            w.setEnabled(enabled)
