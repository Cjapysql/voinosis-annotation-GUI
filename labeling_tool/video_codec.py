"""
OS/OpenCV 빌드마다 mp4 인코딩 가능한 fourcc가 달라서, 여러 후보를 순서대로
시도해보고 실제로 열리는(isOpened()) 첫 번째 코덱을 사용하는 유틸.

우선순위는 OS별로 다르게 잡되(경험적으로 잘 되는 순서), 최종적으로는
"실제로 열어봐서 되는 것"을 쓰기 때문에 어떤 OS/빌드에서든 안전합니다.
"""
import platform
import cv2

_CANDIDATES_BY_OS = {
    "Windows": ["avc1", "H264", "mp4v"],
    "Darwin":  ["avc1", "mp4v"],       # macOS
    "Linux":   ["mp4v", "avc1", "H264"],
}

_cached_fourcc: str | None = None  # 프로세스 내에서 한 번 찾으면 재사용


def get_working_fourcc(sample_size: tuple = (64, 48), fps: float = 30.0) -> str:
    """이 머신/OpenCV 빌드에서 실제로 mp4 인코딩이 되는 fourcc 문자열을 반환."""
    global _cached_fourcc
    if _cached_fourcc is not None:
        return _cached_fourcc

    os_name = platform.system()
    candidates = _CANDIDATES_BY_OS.get(os_name, ["mp4v", "avc1", "H264"])

    import tempfile
    import os as _os

    for codec in candidates:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            writer = cv2.VideoWriter(tmp_path, fourcc, fps, sample_size)
            ok = writer.isOpened()
            writer.release()
        except Exception:
            ok = False
        finally:
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)

        if ok:
            _cached_fourcc = codec
            return codec

    # 아무 후보도 안 되면 마지막 안전값(mp4v)으로 시도 - 대부분의 빌드에서 최소한 열리기는 함
    _cached_fourcc = "mp4v"
    return _cached_fourcc


def make_video_writer(out_path: str, fps: float, frame_size: tuple) -> cv2.VideoWriter:
    codec = get_working_fourcc(sample_size=frame_size, fps=fps)
    fourcc = cv2.VideoWriter_fourcc(*codec)
    return cv2.VideoWriter(str(out_path), fourcc, fps, frame_size)
