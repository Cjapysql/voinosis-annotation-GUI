"""
단일 카메라 스트림(예: driver/rgb)에서 절대시각 t에 해당하는 프레임을 가져온다.

재생 중(순차적으로 시간이 흐르는 경우)에는 cv2 VideoCapture.read()를 그대로
이어서 호출하는 게 set(POS_FRAMES) 탐색보다 훨씬 빠르고 정확해서, 직전에
읽은 위치와 요청 위치를 비교해 순차/탐색을 자동으로 판단한다.
"""
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import cv2

from back.timestamp_index import CameraTimestampIndex


class StreamPlayer:
    def __init__(self, index: CameraTimestampIndex, flip_180: bool = False):
        """flip_180: road 카메라가 광축 기준 180도 돌아간 채 장착돼 있어서,
        화면에 보여주기 전에 180도 회전(상하좌우 동시 반전)해야 하는 스트림에 True."""
        self.index = index
        self.flip_180 = flip_180
        self._cap: Optional[cv2.VideoCapture] = None
        self._cap_path: Optional[Path] = None
        self._local_pos = -1          # 현재 cap에서 마지막으로 읽은 local frame idx
        self._last_frame: Optional[np.ndarray] = None

    def frame_at_time(self, t: float) -> Optional[np.ndarray]:
        result = self.index.frame_at_time(t)
        if result is None:
            return None
        path, local_start = result

        if self._cap is None or self._cap_path != path:
            if self._cap is not None:
                self._cap.release()
            self._cap = cv2.VideoCapture(str(path))
            self._cap_path = path
            self._local_pos = -1

        if local_start == self._local_pos:
            return self._last_frame  # 이미 같은 프레임을 갖고 있음

        if local_start == self._local_pos + 1:
            ok, frame = self._cap.read()            # 순차 재생 (빠름)
        else:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, local_start)  # 탐색 (스크러빙)
            ok, frame = self._cap.read()

        if ok:
            if self.flip_180 and frame is not None:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            self._local_pos = local_start
            self._last_frame = frame
        return self._last_frame

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
