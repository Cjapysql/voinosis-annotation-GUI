"""
카메라 프레임(np.ndarray, BGR) 표시용 QLabel 패널.

두 가지 "빈 화면" 상태를 구분해서 보여준다 (라벨러가 "고장났나?" 헷갈리지 않도록):
  - set_unavailable(): 이 트라이얼에 해당 스트림 자체가 없음 (파일 자체가 없어서
    playback에 등록조차 안 됨) - 세션 내내 고정된 상태.
  - update_frame(None): 스트림은 있는데 지금 이 시각엔 프레임이 없음
    (세그먼트 사이 gap, 녹화 범위 밖 등) - 재생 중 시시각각 바뀔 수 있음.
"""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel


class VideoPanel(QLabel):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.setMinimumSize(240, 180)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #202020; color: #aaa; font-weight: bold;")
        self.setText(title)
        self._unavailable = False

    def set_unavailable(self, reason: str = "이 트라이얼에 해당 스트림 없음"):
        self._unavailable = True
        self.setText(f"{self.title}\n({reason})")
        self.setPixmap(QPixmap())

    def update_frame(self, frame):
        if self._unavailable:
            return  # 애초에 스트림이 없는 패널은 playback에 등록되지 않으므로 보통 호출 안 됨
        if frame is None:
            self.setText(f"{self.title}\n(데이터 없음: 이 시각엔 녹화된 프레임이 없음)")
            self.setPixmap(QPixmap())
            return

        if frame.ndim == 2:
            norm = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            rgb = cv2.cvtColor(norm, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(pixmap)
