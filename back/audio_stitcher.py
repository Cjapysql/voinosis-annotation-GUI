"""
세그먼트로 쪼개진 wav 여러 개를, 세그먼트 사이 무음(gap)까지 반영해 하나의 연속된
wav로 합친다.

PlaybackController가 QMediaPlayer 파일 하나를 마스터 시계로 삼는 구조라서
(front/playback_controller.py 참고), 여러 세그먼트를 그대로는 재생할 수 없다.
재생 전에 미리 이어붙여서 기존 구조를 그대로 쓴다. 결과 파일은 캐시해서
세그먼트 원본이 안 바뀌었으면 재생성하지 않는다.
"""
import wave
from pathlib import Path

from .session_loader import AudioStreamFiles
from .timestamp_index import AudioTimestampIndex


def build_continuous_audio(audio: AudioStreamFiles, cache_dir: Path) -> tuple[Path, float] | None:
    """반환: (이어붙인 wav 경로, 그 wav 0초 지점의 절대 unix time) / 불가능하면 None."""
    if not audio.segment_files or not audio.timestamp_csv:
        return None

    index = AudioTimestampIndex(audio.timestamp_csv, audio.segment_files)
    if not index.segment_starts:
        return None
    base_ts = index.segment_starts[0]

    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{audio.mic_name}_stitched.wav"

    newest_src_mtime = max(p.stat().st_mtime for _, p in audio.segment_files)
    if out_path.exists() and out_path.stat().st_mtime >= newest_src_mtime:
        return out_path, base_ts

    params = None
    cursor_ts = base_ts
    with wave.open(str(out_path), "wb") as out:
        for i, (_seg_num, path) in enumerate(audio.segment_files):
            with wave.open(str(path), "rb") as wf:
                if params is None:
                    params = wf.getparams()
                    out.setparams(params)
                seg_start = index.segment_starts[i]
                gap = seg_start - cursor_ts
                if gap > 0:
                    silence_frames = int(gap * params.framerate)
                    out.writeframesraw(
                        b"\x00" * (silence_frames * params.sampwidth * params.nchannels)
                    )
                out.writeframesraw(wf.readframes(wf.getnframes()))
                cursor_ts = seg_start + wf.getnframes() / params.framerate

    return out_path, base_ts
