"""
시나리오(distraction/drowsiness/cognitive) 공통 라벨링 페이지.

boundaries_locked=True인 시나리오(drowsiness, cognitive)는 TaskWindow에서
파생된 구간을 그대로 쓰고 라벨러는 라벨 값만 확인/수정합니다.
boundaries_locked=False인 시나리오(distraction)는 라벨러가 재생하면서
"시작점 지정"/"끝점 지정" 버튼으로 직접 구간을 잘라 여러 개 만들 수 있습니다
(복합 동작을 여러 서브구간으로 나누는 경우 대응).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from back.models import Scenario, TaskWindow, DistractionTaskWindow, CognitiveTaskWindow, LabelDraft
from back.session_loader import TrialData
from back.timestamp_index import CameraTimestampIndex
from back.draft_store import DraftStore
from back.segment_exporter import SegmentExporter
from back.label_taxonomy import AreaTaxonomy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QListWidget, QListWidgetItem
)

from widgets.timeline_widget import TimelineWidget, TimelineMarker
from widgets.video_panel import VideoPanel
from widgets.label_forms import DistractionLabelForm, DrowsinessLabelForm, CognitiveLabelForm
from stream_player import StreamPlayer
from playback_controller import PlaybackController

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
    def __init__(self, scenario: Scenario, trial: TrialData, task_windows: list[TaskWindow],
                 draft_store: DraftStore, exporter: SegmentExporter,
                 areas: list[AreaTaxonomy], parent=None):
        super().__init__(parent)
        self.scenario = scenario
        self.trial = trial
        self.task_windows = task_windows
        self.draft_store = draft_store
        self.exporter = exporter
        self.areas = areas
        self.boundaries_locked = scenario in (Scenario.DROWSINESS, Scenario.COGNITIVE)

        self.current_window: TaskWindow | None = None
        self.pending_start: float | None = None
        self.pending_end: float | None = None

        self._build_camera_indices()
        self._build_ui()
        self._build_playback()

        if self.task_windows:
            self._load_task_window(self.task_windows[0])

    # ------------------------------------------------------------------
    def _build_camera_indices(self):
        self.camera_indices: dict[tuple, CameraTimestampIndex] = {}
        all_starts, all_ends = [], []
        for (position, modality), stream in self.trial.cameras.items():
            if not stream.timestamp_csv or not stream.segment_files:
                continue
            idx = CameraTimestampIndex(stream.timestamp_csv, stream.segment_files)
            self.camera_indices[(position, modality)] = idx
            if idx._frame_t_sec:
                all_starts.append(idx._frame_t_sec[0])
                all_ends.append(idx._frame_t_sec[-1])
        self.total_start = min(all_starts) if all_starts else 0.0
        self.total_end = max(all_ends) if all_ends else 1.0

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        self.timeline = TimelineWidget()
        self.timeline.set_range(self.total_start, self.total_end)
        self.timeline.position_clicked.connect(self._on_timeline_clicked)
        left.addWidget(self.timeline)

        grid = QGridLayout()
        self.video_panels: dict[str, VideoPanel] = {}
        for i, (position, modality, title) in enumerate(DISPLAY_STREAMS):
            panel = VideoPanel(title)
            self.video_panels[f"{position}_{modality}"] = panel
            grid.addWidget(panel, i // 3, i % 3)
        grid_widget = QWidget()
        grid_widget.setLayout(grid)
        left.addWidget(grid_widget, stretch=1)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("재생")
        self.pause_btn = QPushButton("일시정지")
        self.stop_btn = QPushButton("정지")
        transport.addWidget(self.play_btn)
        transport.addWidget(self.pause_btn)
        transport.addWidget(self.stop_btn)
        left.addLayout(transport)

        outer.addLayout(left, stretch=3)

        # ---- 우측 사이드 패널 ----
        side = QVBoxLayout()
        side.addWidget(QLabel(f"<b>태스크: {self.scenario.value}</b>"))

        side.addWidget(QLabel("불러오기"))
        self.window_combo = QComboBox()
        self.window_combo.addItems([w.window_id for w in self.task_windows])
        self.window_combo.currentIndexChanged.connect(self._on_window_selected)
        side.addWidget(self.window_combo)

        self.label_form = self._make_label_form()
        side.addWidget(self.label_form)

        if not self.boundaries_locked:
            mark_row = QHBoxLayout()
            self.mark_start_btn = QPushButton("시작점 지정")
            self.mark_end_btn = QPushButton("끝점 지정")
            self.mark_start_btn.clicked.connect(self._on_mark_start)
            self.mark_end_btn.clicked.connect(self._on_mark_end)
            mark_row.addWidget(self.mark_start_btn)
            mark_row.addWidget(self.mark_end_btn)
            side.addLayout(mark_row)

        self.save_draft_btn = QPushButton("이 구간 저장 (작업중에 추가)")
        self.save_draft_btn.clicked.connect(self._on_save_draft)
        side.addWidget(self.save_draft_btn)

        side.addWidget(QLabel("작업 중인 구간들"))
        self.draft_list = QListWidget()
        side.addWidget(self.draft_list)

        self.final_commit_btn = QPushButton("최종 저장 (모두 커밋)")
        self.final_commit_btn.setStyleSheet("background-color: #2ecc71; font-weight: bold;")
        self.final_commit_btn.clicked.connect(self._on_final_commit)
        side.addWidget(self.final_commit_btn)

        side.addStretch()
        outer.addLayout(side, stretch=2)

        self.play_btn.clicked.connect(lambda: self.playback.play())
        self.pause_btn.clicked.connect(lambda: self.playback.pause())
        self.stop_btn.clicked.connect(lambda: self.playback.stop())

    def _make_label_form(self) -> QWidget:
        if self.scenario == Scenario.DISTRACTION:
            return DistractionLabelForm(self.areas)
        elif self.scenario == Scenario.DROWSINESS:
            return DrowsinessLabelForm()
        else:
            return CognitiveLabelForm()

    # ------------------------------------------------------------------
    def _build_playback(self):
        self.playback = PlaybackController(self.total_start, self.total_end, parent=self)
        self.playback.time_changed.connect(self.timeline.set_playhead)

        for position, modality, _title in DISPLAY_STREAMS:
            key = f"{position}_{modality}"
            idx = self.camera_indices.get((position, modality))
            if idx is None:
                continue
            player = StreamPlayer(idx)
            panel = self.video_panels[key]
            self.playback.register_stream(key, player, panel.update_frame)

        dashboard = self.trial.audio.get("dashboard_mic")
        if dashboard and dashboard.get("wav") and dashboard.get("timestamp_csv"):
            import csv
            with open(dashboard["timestamp_csv"], "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if rows:
                base_ts = float(rows[0]["timestamp"])
                self.playback.set_audio(dashboard["wav"], base_ts)

        self.playback.seek_to(self.total_start)

    # ------------------------------------------------------------------
    def _on_timeline_clicked(self, ts: float):
        self.playback.seek_to(ts)

    def _on_window_selected(self, idx: int):
        if 0 <= idx < len(self.task_windows):
            self._load_task_window(self.task_windows[idx])

    def _load_task_window(self, window: TaskWindow):
        self.current_window = window
        self.pending_start, self.pending_end = None, None
        self.timeline.set_pending_selection(None, None)

        markers = [TimelineMarker(w.window_id, w.start_ts, w.end_ts, MARKER_COLORS[self.scenario])
                   for w in self.task_windows]
        self.timeline.set_task_markers(markers)
        self._refresh_draft_markers()

        if self.boundaries_locked:
            if self.scenario == Scenario.DROWSINESS and isinstance(window, DistractionTaskWindow):
                start_dt, end_dt = window.drowsiness_window
                self.pending_start, self.pending_end = start_dt.timestamp(), end_dt.timestamp()
                self.label_form.set_prefill_kss(window.kss_score)
            elif self.scenario == Scenario.COGNITIVE and isinstance(window, CognitiveTaskWindow):
                self.pending_start, self.pending_end = window.start_ts, window.end_ts
                self.label_form.set_prefill(window.task_name, window.difficulty)
            self.timeline.set_pending_selection(self.pending_start, self.pending_end)
            self.playback.seek_to(self.pending_start)
        else:
            if isinstance(window, DistractionTaskWindow):
                self.label_form.set_hint(window.distraction_task_text)
            self.playback.seek_to(window.start_ts)

        self._refresh_draft_list()

    # ------------------------------------------------------------------
    def _on_mark_start(self):
        self.pending_start = self._current_playhead_ts()
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)

    def _on_mark_end(self):
        self.pending_end = self._current_playhead_ts()
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)

    def _current_playhead_ts(self) -> float:
        return self.timeline.playhead_ts

    # ------------------------------------------------------------------
    def _on_save_draft(self):
        if self.pending_start is None or self.pending_end is None or self.pending_start >= self.pending_end:
            QMessageBox.warning(self, "구간 필요", "시작점과 끝점을 먼저 지정해주세요.")
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

    def _refresh_draft_markers(self):
        drafts = self.draft_store.drafts_for_scenario(self.scenario)
        markers = [TimelineMarker(f"draft:{d.draft_id}", d.start_ts, d.end_ts, "#d0021b")
                   for d in drafts]
        self.timeline.set_draft_markers(markers)

    def _refresh_draft_list(self):
        self.draft_list.clear()
        if self.current_window is None:
            return
        drafts = [d for d in self.draft_store.drafts_for_scenario(self.scenario)
                  if d.source_window_id == self.current_window.window_id]
        for i, d in enumerate(drafts, start=1):
            item = QListWidgetItem(f"Seg{i}  [{d.start_ts:.2f} ~ {d.end_ts:.2f}]  {d.label_fields}")
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

        for d in drafts:
            cognitive_task_name = None
            if self.scenario == Scenario.COGNITIVE:
                window = next((w for w in self.task_windows if w.window_id == d.source_window_id), None)
                if isinstance(window, CognitiveTaskWindow):
                    cognitive_task_name = window.task_name
            self.exporter.export_draft(d, cognitive_task_name=cognitive_task_name)
            self.draft_store.mark_committed(d.draft_id)

        self._refresh_draft_markers()
        self._refresh_draft_list()
        QMessageBox.information(self, "완료", "최종 저장이 완료되었습니다.")
