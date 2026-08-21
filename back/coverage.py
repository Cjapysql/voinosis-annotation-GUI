"""
센서별 대략적인 커버리지(세그먼트마다 첫 시각 ~ 마지막 시각)를 가볍게 조회한다.

CameraTimestampIndex/AudioTimestampIndex/RadarTimestampIndex처럼 프레임/샘플
단위로 정확하게 인덱싱하는 게 아니라, 세그먼트(csv 파일)마다 첫 행과 마지막 행
시각만 읽어서 "대략 이 시간대에 데이터가 있다"는 정도만 빠르게 파악한다 -
라벨링 화면의 "이 구간에 데이터가 없습니다" 경고 배너처럼 정확도보다 속도가
중요한 곳에서만 쓴다.

세그먼트 전체를 하나의 구간(첫 세그먼트 시작~마지막 세그먼트 끝)으로 뭉치면
안 된다 - 세그먼트 사이에 녹화가 아예 없던 공백(예: 오디오가 중간에 1시간
끊긴 경우)까지 "커버됨"으로 오인하게 되어, 정작 잡아야 할 사례를 놓친다.
그래서 세그먼트별 (시작, 끝) 쌍을 리스트로 유지하고, 특정 구간이 데이터가
있는지는 그 리스트의 세그먼트들과 개별적으로 겹치는지 확인해야 한다.
"""
import csv
from pathlib import Path

_SENSOR_T_COLS = ("동기화기준시각_sec", "t_sec", "ros_time_sec", "timestamp")


def _csv_first_last_t_sec(csv_path: Path, t_col_candidates=_SENSOR_T_COLS) -> tuple[float, float] | None:
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return None
            t_col = next((c for c in t_col_candidates if c in header), None)
            if t_col is None:
                return None
            idx = header.index(t_col)
            first_row = next(reader, None)
            if first_row is None:
                return None
            first_t = float(first_row[idx])
            last_t = first_t
            for row in reader:
                if row:
                    last_t = float(row[idx])
    except (OSError, ValueError, IndexError):
        return None
    return (first_t, last_t)


def _audio_stream_segments(stream) -> list[tuple[float, float]]:
    """세그먼트별 (시작, 끝) 리스트 - 세그먼트 사이 공백은 그냥 리스트에 안 남기는
    걸로 자연스럽게 표현됨(공백 구간을 커버하는 원소가 없으므로)."""
    ranges = []
    for _seg_num, _media_path, ts_path in stream.segment_files:
        if ts_path is None:
            continue
        r = _csv_first_last_t_sec(ts_path)
        if r is not None:
            ranges.append(r)
    return ranges


def _csv_list_segments(csv_paths: list) -> list[tuple[float, float]]:
    ranges = []
    for p in csv_paths:
        r = _csv_first_last_t_sec(p)
        if r is not None:
            ranges.append(r)
    return ranges


def _radar_segments(raw_dir) -> list[tuple[float, float]]:
    if raw_dir is None or not Path(raw_dir).exists():
        return []
    seg_dirs = sorted(
        (p for p in Path(raw_dir).iterdir() if p.is_dir() and p.name.startswith("seg")),
        key=lambda p: p.name,
    )
    ranges = []
    for seg_dir in seg_dirs:
        csv_path = next(seg_dir.glob("radar_frame_index_*.csv"), None)
        if csv_path is None:
            continue
        r = _csv_first_last_t_sec(csv_path)
        if r is not None:
            ranges.append(r)
    return ranges


def compute_sensor_coverage(trial) -> dict[str, list[tuple[float, float]]]:
    """trial(TrialData) -> {표시용 이름: [(세그먼트1 시작,끝), (세그먼트2 시작,끝), ...]}.
    카메라는 이미 CameraTimestampIndex로 정확하게 계산되므로 여기 포함하지 않는다 -
    호출부가 camera_indices를 따로 갖고 있으니 그걸 그대로 쓰면 된다."""
    coverage = {}
    for mic_name, stream in trial.audio.items():
        segs = _audio_stream_segments(stream)
        if segs:
            coverage[f"오디오({mic_name})"] = segs
    for name, paths in trial.imu.items():
        segs = _csv_list_segments(paths)
        if segs:
            coverage[f"IMU({name})"] = segs
    for name, paths in trial.watch.items():
        segs = _csv_list_segments(paths)
        if segs:
            coverage[f"워치({name})"] = segs
    segs = _radar_segments(trial.radar.get("raw_dir"))
    if segs:
        coverage["레이더"] = segs
    return coverage


def range_overlaps_any(start_ts: float, end_ts: float, segments: list[tuple[float, float]]) -> bool:
    """[start_ts, end_ts]가 segments(세그먼트별 (시작,끝) 리스트) 중 하나라도와 겹치는지."""
    return any(seg_start <= end_ts and start_ts <= seg_end for seg_start, seg_end in segments)
