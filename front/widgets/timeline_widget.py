"""
타임라인 위젯.

전체 트라이얼 구간(total_start~total_end)을 하나의 가로 바로 그리고:
  - TaskWindow들을 위쪽에 구간 브래킷 + 이름으로 표시 (survey json에서 자동 생성된 것)
  - 확정 전 LabelDraft들을 반투명 색상 구간으로 표시
  - 현재 재생 위치(playhead)를 세로선으로 표시
  - 클릭하면 그 위치로 seek (position_clicked 시그널)

PDF의 드래그 핸들(●) 방식 대신, "시작점 지정"/"끝점 지정" 버튼으로 현재
playhead 위치를 캡처하는 방식을 씁니다. 마우스 드래그 픽셀 계산은 이 환경에서
시각적으로 검증할 수 없어서, 클릭-seek + 버튼 캡처 조합이 훨씬 신뢰도가 높습니다
(기능적으로는 동일하게 "구간 시작/끝 지점 선택"을 지원함).
"""
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import QWidget


@dataclass
class TimelineMarker:
    label: str
    start_ts: float
    end_ts: float
    color: str = "#4a90d9"


class TimelineWidget(QWidget):
    position_clicked = Signal(float)  # 클릭한 절대시각

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.total_start = 0.0
        self.total_end = 1.0
        self.playhead_ts: float = 0.0
        self.task_markers: list[TimelineMarker] = []
        self.draft_markers: list[TimelineMarker] = []
        self.pending_start: float | None = None   # "시작점 지정"으로 찍은 임시 시작점
        self.pending_end: float | None = None

    def set_range(self, start_ts: float, end_ts: float):
        self.total_start = start_ts
        self.total_end = max(end_ts, start_ts + 1e-6)
        self.update()

    def set_task_markers(self, markers: list[TimelineMarker]):
        self.task_markers = markers
        self.update()

    def set_draft_markers(self, markers: list[TimelineMarker]):
        self.draft_markers = markers
        self.update()

    def set_playhead(self, ts: float):
        self.playhead_ts = ts
        self.update()

    def set_pending_selection(self, start_ts: float | None, end_ts: float | None):
        self.pending_start = start_ts
        self.pending_end = end_ts
        self.update()

    # ------------------------------------------------------------------
    def _ts_to_x(self, ts: float) -> float:
        span = self.total_end - self.total_start
        if span <= 0:
            return 0.0
        ratio = (ts - self.total_start) / span
        return ratio * self.width()

    def _x_to_ts(self, x: float) -> float:
        span = self.total_end - self.total_start
        ratio = max(0.0, min(1.0, x / max(1, self.width())))
        return self.total_start + ratio * span

    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        track_y = h * 0.55
        track_h = 10

        # 배경 트랙
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e0e0e0"))
        painter.drawRoundedRect(QRectF(0, track_y, w, track_h), 3, 3)

        # task window 마커 (상단 브래킷 + 라벨)
        for m in self.task_markers:
            x0, x1 = self._ts_to_x(m.start_ts), self._ts_to_x(m.end_ts)
            painter.setPen(QPen(QColor(m.color), 2))
            painter.drawLine(int(x0), int(track_y - 15), int(x0), int(track_y - 5))
            painter.drawLine(int(x1), int(track_y - 15), int(x1), int(track_y - 5))
            painter.drawLine(int(x0), int(track_y - 15), int(x1), int(track_y - 15))
            painter.drawText(int(x0), int(track_y - 20), m.label)

        # 확정 전 draft 구간 (반투명 색)
        for m in self.draft_markers:
            x0, x1 = self._ts_to_x(m.start_ts), self._ts_to_x(m.end_ts)
            color = QColor(m.color)
            color.setAlpha(120)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(x0, track_y, max(2, x1 - x0), track_h))

        # 현재 작업 중인 pending 선택 구간
        if self.pending_start is not None:
            end = self.pending_end if self.pending_end is not None else self.playhead_ts
            x0, x1 = self._ts_to_x(self.pending_start), self._ts_to_x(end)
            painter.setBrush(QBrush(QColor(220, 80, 80, 90)))
            painter.setPen(QPen(QColor(200, 40, 40), 1))
            painter.drawRect(QRectF(min(x0, x1), track_y - 2, abs(x1 - x0), track_h + 4))

        # playhead
        px = self._ts_to_x(self.playhead_ts)
        painter.setPen(QPen(QColor("#d0021b"), 2))
        painter.drawLine(int(px), 0, int(px), h)

    def mousePressEvent(self, event):
        ts = self._x_to_ts(event.position().x())
        self.position_clicked.emit(ts)
