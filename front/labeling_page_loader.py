"""
LabelingPage를 실제로 만들기 전에 필요한 무거운 계산(카메라 세그먼트별
timestamp csv 파싱 + 오디오 세그먼트 이어붙이기)을 백그라운드 스레드에서
먼저 끝내두는 로더.

카메라 인덱스 생성(back/timestamp_index.py) + 오디오 스티칭(back/audio_stitcher.py)은
전부 Qt에 의존하지 않는 back/ 계층 로직이라 스레드에서 안전하게 돌릴 수 있다.
반면 LabelingPage 자체(QWidget)는 반드시 메인 스레드에서 만들어야 하므로,
이 로더가 끝낸 결과(camera_indices, 기본 마이크 이름, 오디오 스티칭 결과)를
LabelingPage 생성자에 미리 계산된 값으로 넘겨서, 생성자 자체는 순식간에
끝나게 한다 - "라벨링 시작" 눌렀을 때 화면 전환이 멈춰서 OS가 "응답 없음"을
띄우던 문제를 막기 위함.
"""
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from back.session_loader import TrialData
from back.timestamp_index import CameraTimestampIndex
from back.audio_stitcher import build_continuous_audio

# front/labeling_page.py의 DISPLAY_STREAMS 우선순위와 반드시 같은 순서를 유지해야 함
# (오디오 세그먼트 경계 판단 기준 스트림을 그쪽과 동일하게 고르기 위함)
_DISPLAY_STREAM_KEYS = [
    ("driver", "rgb"), ("behavior", "rgb"), ("road", "rgb"),
    ("driver", "infrared"), ("behavior", "infrared"), ("road", "infrared"),
]


def _reference_segment_starts(camera_indices: dict, expected_count: int) -> list[float] | None:
    for key in _DISPLAY_STREAM_KEYS:
        idx = camera_indices.get(key)
        if idx is None:
            continue
        starts = idx.segment_starts
        if starts and len(starts) == expected_count:
            return starts
    return None


class LabelingPageDataLoader(QThread):
    # camera_indices는 튜플 키를 가진 dict라 Signal(dict, ...)로 선언하면 PySide6가
    # 스레드 간 큐잉 시 C++ 타입으로 변환하려다 실패한다(dict 값이 CameraTimestampIndex
    # 커스텀 객체라서 더더욱) - object로 선언해서 그냥 파이썬 객체 그대로 넘긴다.
    loaded = Signal(object, object, object)  # (camera_indices, default_mic_name|None, audio_result|None)
    failed = Signal(str)

    def __init__(self, trial: TrialData, audio_cache_dir: Path, parent=None):
        super().__init__(parent)
        self.trial = trial
        self.audio_cache_dir = audio_cache_dir

    def run(self):
        try:
            camera_indices: dict[tuple, CameraTimestampIndex] = {}
            for key, stream in self.trial.cameras.items():
                if stream.segment_files:
                    camera_indices[key] = CameraTimestampIndex(stream.segment_files)

            default_mic_name = None
            audio_result = None
            mic_names = [name for name, stream in self.trial.audio.items() if stream.segment_files]
            if mic_names:
                default_mic_name = "ecms1_audio" if "ecms1_audio" in mic_names else mic_names[0]
                mic_stream = self.trial.audio[default_mic_name]
                reference_starts = _reference_segment_starts(camera_indices, len(mic_stream.segment_files))
                audio_result = build_continuous_audio(
                    mic_stream, self.audio_cache_dir, reference_segment_starts=reference_starts
                )
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.loaded.emit(camera_indices, default_mic_name, audio_result)
