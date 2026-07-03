"""
카메라 프레임(np.ndarray, BGR) 표시용 QLabel 패널.
None이 들어오면 "프레임 없음" 상태를 표시 (해당 시각에 그 스트림 데이터가 없는 경우).
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

    def update_frame(self, frame):
        if frame is None:
            self.setText(f"{self.title}\n(데이터 없음)")
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
