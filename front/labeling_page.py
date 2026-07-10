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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QListWidget, QListWidgetItem
)

from front.widgets.timeline_widget import TimelineWidget, TimelineMarker
from front.widgets.video_panel import VideoPanel
from front.widgets.label_forms import DistractionLabelForm, DrowsinessLabelForm, CognitiveLabelForm
from front.stream_player import StreamPlayer
from front.playback_controller import PlaybackController

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

    def __init__(self, scenario: Scenario, trial: TrialData, task_windows: list[TaskWindow],
                 draft_store: DraftStore, exporter: SegmentExporter,
                 areas: list[AreaTaxonomy], audio_cache_dir: Path, parent=None):
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

        self._build_camera_indices()
        self._build_ui()
        self._build_playback()

        if self.task_windows:
            self._load_task_window(self.task_windows[0])
        self._refresh_progress_label()

        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            if self.playback.is_playing:
                self.playback.pause()
            else:
                self.playback.play()
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
        self.playback.seek_to(self.timeline.playhead_ts + direction * self.frame_step_sec)

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
    def _build_ui(self):
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
        zoom_hint = QLabel("휠: 확대/축소 · 우클릭 드래그: 이동")
        zoom_hint.setStyleSheet("color: #888;")
        zoom_row.addWidget(zoom_hint)
        zoom_row.addStretch()
        left.addLayout(zoom_row)

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
        self.window_combo.currentIndexChanged.connect(self._on_window_selected)
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
            panel = self.video_panels[key]
            if idx is None:
                panel.set_unavailable()
                continue
            player = StreamPlayer(idx)
            self.playback.register_stream(key, player, panel.update_frame)

        mic = self._select_audio_stream()
        if mic is not None:
            result = build_continuous_audio(mic, self.audio_cache_dir)
            if result is not None:
                wav_path, base_ts = result
                self.playback.set_audio(wav_path, base_ts)

        self.playback.seek_to(self.total_start)

    def _select_audio_stream(self):
        """오디오는 마이크 하나만 마스터 시계로 쓰면 되므로, 세그먼트+timestamp가
        온전한 마이크 중 첫 번째를 고른다 (예: byv20처럼 timestamp csv만 있고
        wav 세그먼트가 없는 마이크는 건너뜀)."""
        for stream in self.trial.audio.values():
            if stream.segment_files and stream.timestamp_csv:
                return stream
        return None

    # ------------------------------------------------------------------
    def _on_timeline_clicked(self, ts: float):
        self.playback.seek_to(ts)

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
            if not idx._frame_t_sec:
                continue
            if idx._frame_t_sec[0] <= end_ts and start_ts <= idx._frame_t_sec[-1]:
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
        self.pending_start = self._current_playhead_ts()
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)

    def _on_mark_end(self):
        self.pending_end = self._current_playhead_ts()
        self.timeline.set_pending_selection(self.pending_start, self.pending_end)

    def _on_reset_to_guideline(self):
        """자동 계산값(또는 distraction은 instruction 전체 구간)으로 되돌림."""
        if self.current_window is None:
            return
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

    def _on_delete_draft(self):
        draft_id = self._selected_draft_id()
        if draft_id is None:
            QMessageBox.information(self, "선택 필요", "삭제할 구간을 목록에서 먼저 선택해주세요.")
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
            window = next((w for w in self.task_windows if w.window_id == d.source_window_id), None)
            cognitive_task_name = window.task_name if isinstance(window, CognitiveTaskWindow) else None
            self.exporter.export_draft(d, cognitive_task_name=cognitive_task_name, source_window=window)
            self.draft_store.mark_committed(d.draft_id)

        self._refresh_draft_markers()
        self._refresh_draft_list()
        self._refresh_progress_label()
        QMessageBox.information(self, "완료", "최종 저장이 완료되었습니다.")
