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

전체 세션(수십 분)이 고정폭 바 하나에 매핑되면 몇 초짜리 액션을 픽셀 단위로
정밀하게 자르기 어려워서, total_start~total_end(전체 범위)와 별개로
view_start~view_end(현재 보이는 확대 범위)를 두고 화면 좌표 변환은 항상 view
기준으로 계산한다. 휠로 확대/축소, 우클릭 드래그로 이동한다.
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

    MIN_VIEW_SPAN_SEC = 2.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.total_start = 0.0
        self.total_end = 1.0
        self.view_start = 0.0   # 현재 확대/이동된 화면에 보이는 범위
        self.view_end = 1.0
        self.playhead_ts: float = 0.0
        self.task_markers: list[TimelineMarker] = []
        self.draft_markers: list[TimelineMarker] = []
        self.pending_start: float | None = None   # "시작점 지정"으로 찍은 임시 시작점
        self.pending_end: float | None = None
        self._pan_last_x: float | None = None

    def set_range(self, start_ts: float, end_ts: float):
        self.total_start = start_ts
        self.total_end = max(end_ts, start_ts + 1e-6)
        self.view_start = self.total_start
        self.view_end = self.total_end
        self.update()

    def set_view_range(self, start_ts: float, end_ts: float):
        """확대/이동된 화면 범위를 지정. total 범위 밖으로는 못 벗어나게 clamp."""
        total_span = self.total_end - self.total_start
        span = max(end_ts - start_ts, min(self.MIN_VIEW_SPAN_SEC, total_span))
        span = min(span, total_span)
        start_ts = max(self.total_start, min(start_ts, self.total_end - span))
        self.view_start = start_ts
        self.view_end = start_ts + span
        self.update()

    def zoom_to_fit(self, start_ts: float, end_ts: float, padding_ratio: float = 0.2):
        """특정 구간(예: 현재 작업 중인 instruction 구간)이 여백을 두고 화면에 꽉 차게."""
        span = max(end_ts - start_ts, 1e-6)
        pad = span * padding_ratio
        self.set_view_range(start_ts - pad, end_ts + pad)

    def reset_view(self):
        self.set_view_range(self.total_start, self.total_end)

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
        span = self.view_end - self.view_start
        if span <= 0:
            return 0.0
        ratio = (ts - self.view_start) / span
        x = ratio * self.width()
        # 마커 시각이 보이는 범위를 크게 벗어나면(센서 간 시계 어긋남 등) ratio가
        # 극단적으로 커져서 int 캐스팅 시 오버플로우/크래시가 날 수 있어 안전 범위로 clamp.
        # (화면 밖으로 살짝 넘어가는 정도는 그대로 두고, 그림이 깨지지 않을 정도만 제한)
        return max(-1_000_000.0, min(1_000_000.0, x))

    def _x_to_ts(self, x: float) -> float:
        span = self.view_end - self.view_start
        ratio = max(0.0, min(1.0, x / max(1, self.width())))
        return self.view_start + ratio * span

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

        # 확대 중일 때만: 전체 범위 대비 현재 보이는 구간이 어디인지 맨 위에 미니 오버뷰로 표시
        if self.view_start > self.total_start + 1e-6 or self.view_end < self.total_end - 1e-6:
            total_span = max(self.total_end - self.total_start, 1e-9)
            ov_x0 = (self.view_start - self.total_start) / total_span * w
            ov_x1 = (self.view_end - self.total_start) / total_span * w
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#cccccc"))
            painter.drawRect(QRectF(0, 0, w, 4))
            painter.setBrush(QColor("#4a90d9"))
            painter.drawRect(QRectF(ov_x0, 0, max(2, ov_x1 - ov_x0), 4))

    def wheelEvent(self, event):
        """휠로 커서 위치를 중심으로 확대/축소."""
        angle = event.angleDelta().y()
        if angle == 0:
            return
        factor = 0.85 if angle > 0 else 1 / 0.85
        cursor_ts = self._x_to_ts(event.position().x())
        span = self.view_end - self.view_start
        new_span = span * factor
        ratio = (cursor_ts - self.view_start) / span if span > 0 else 0.5
        new_start = cursor_ts - ratio * new_span
        self.set_view_range(new_start, new_start + new_span)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._pan_last_x = event.position().x()
            return
        ts = self._x_to_ts(event.position().x())
        self.position_clicked.emit(ts)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.RightButton and self._pan_last_x is not None:
            dx = event.position().x() - self._pan_last_x
            self._pan_last_x = event.position().x()
            span = self.view_end - self.view_start
            dt = -dx / max(1, self.width()) * span
            self.set_view_range(self.view_start + dt, self.view_end + dt)
            return
        if event.buttons() & Qt.LeftButton:
            ts = self._x_to_ts(event.position().x())
            self.position_clicked.emit(ts)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self._pan_last_x = None
