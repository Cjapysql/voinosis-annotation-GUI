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


def build_continuous_audio(audio: AudioStreamFiles, cache_dir: Path,
                            reference_segment_starts: list[float] | None = None) -> tuple[Path, float] | None:
    """반환: (이어붙인 wav 경로, 그 wav 0초 지점의 절대 unix time) / 불가능하면 None.

    reference_segment_starts: 비디오 쪽에서 계산한 세그먼트 시작 시각(신뢰도 높음).
    오디오 자체 timestamp csv는 청크 단위라 sparse해서, 일부 세그먼트만 실측
    데이터가 있으면 엉뚱한 세그먼트로 오인하는 사고가 날 수 있다 (실제로 발생함:
    csv에 세그먼트 하나 분량만 남아있었는데 그걸 첫 번째 세그먼트로 착각해서,
    그 세그먼트의 진짜 오디오가 완전히 다른 시각대의 소리로 재생됐었음). 그래서
    가능하면 이 값을 그대로 받아써서 세그먼트 경계 판단을 비디오에 맡긴다.
    """
    if not audio.segment_files:
        return None

    index = AudioTimestampIndex(audio.segment_files, reference_segment_starts=reference_segment_starts)
    if not index.segment_starts:
        return None
    base_ts = index.segment_starts[0]

    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{audio.mic_name}_stitched.wav"

    newest_src_mtime = max(p.stat().st_mtime for _, p, _ts in audio.segment_files)
    if out_path.exists() and out_path.stat().st_mtime >= newest_src_mtime:
        return out_path, base_ts

    # PlaybackController.seek_to()는 "경과 시간(절대시각-base_ts) == 파일 위치"라는
    # 단순 선형 공식을 쓰기 때문에, 이 파일은 처음부터 끝까지 그 관계가 어긋나면
    # 안 된다. 그런데 같은 세그먼트라도 비디오 파일 길이와 오디오 파일 길이가
    # 미세하게 다르다(실측: 세그먼트당 최대 1.5초, 항상 오디오가 더 김). 그래서
    # 각 세그먼트는 "다음 세그먼트가 시작해야 할 시각"까지만 쓰고, 넘치는 꼬리는
    # 잘라낸다(자기 길이가 짧으면 반대로 무음으로 채워짐 - 다음 반복의 gap 처리가
    # 자동으로 해줌). 이렇게 하면 세그먼트 경계마다 커서가 항상 정확히 비디오가
    # 선언한 시각과 일치해서, 절대시각 -> 파일위치 매핑이 끝까지 선형으로 유지된다.
    params = None
    cursor_ts = base_ts
    with wave.open(str(out_path), "wb") as out:
        for i, (_seg_num, path, _ts) in enumerate(audio.segment_files):
            with wave.open(str(path), "rb") as wf:
                if params is None:
                    params = wf.getparams()
                    out.setparams(params)
                video_seg_start = index.segment_starts[i]
                gap = video_seg_start - cursor_ts
                if gap > 0:
                    silence_frames = int(gap * params.framerate)
                    out.writeframesraw(
                        b"\x00" * (silence_frames * params.sampwidth * params.nchannels)
                    )
                    cursor_ts += gap

                if i + 1 < len(index.segment_starts):
                    allotted = index.segment_starts[i + 1] - cursor_ts
                else:
                    allotted = None  # 마지막 세그먼트는 자를 다음 경계가 없음

                own_duration = wf.getnframes() / params.framerate
                if allotted is not None and own_duration > allotted:
                    frames_to_write = max(0, int(round(allotted * params.framerate)))
                    out.writeframesraw(wf.readframes(frames_to_write))
                    cursor_ts += frames_to_write / params.framerate
                else:
                    out.writeframesraw(wf.readframes(wf.getnframes()))
                    cursor_ts += own_duration

    return out_path, base_ts
