"""
스트림별 (절대시각 <-> 프레임/샘플 위치) 매핑. t_sec을 모든 센서 공통의 정렬
축으로 삼고, 세그먼트 파일 여러 개에 걸친 프레임/샘플을 그 축 위에서 정확한
파일 하나로 되돌려 매핑하는 게 이 모듈의 역할이다.

카메라: 예전엔 "각 seg 파일의 실제 프레임 수(cv2로 조회)를 이용해 전역 frame_idx를
파일 경계로 나눈다"는 방식이었는데, 이건 timestamp csv가 정말로 모든 세그먼트에
걸쳐 빠짐없이 누적돼 있어야만 맞는 방식이었다. csv가 세그먼트 일부만 담고 있으면
(실제로 관측된 사례) "행 번호"와 "그 세그먼트 파일 안에서의 프레임 번호"가 어긋나서
엉뚱한 세그먼트 파일을 가리키는 버그가 생겼다.

지금은 오디오와 같은 방식으로: timestamp csv 안에서 t_sec이 크게 점프하는
지점(녹화가 끊겼다가 다시 시작된 지점)을 세그먼트 경계로 직접 찾고, 그 경계로
나뉜 행 구간을 seg_num 순서대로 세그먼트 파일에 매칭한다. 프레임 개수를 별도로
세어 누적하지 않기 때문에, 로그된 행과 실제 인코딩된 프레임 수가 어긋나도(혹은
csv가 일부 세그먼트만 담고 있어도) 실제로 있는 t_sec 값만 가지고 올바른 파일을
가리킬 수 있다.

오디오: timestamp csv는 카메라와 같은 스키마(frame_idx, t_sec, ...)지만 한 행이
raw 샘플 1개가 아니라 청크(가변 길이) 이벤트라서 카메라처럼 "행 순서 = 프레임
순서"로 1:1 대응시킬 수 없음. 세그먼트 시작 절대시각만 구한 뒤 그 안에서는 표본
레이트가 일정하다는 가정으로 절대시각 -> 로컬 샘플 인덱스를 선형 계산.
"""
import bisect
import csv as csv_mod
import wave
from pathlib import Path


class CameraTimestampIndex:
    GAP_THRESHOLD_SEC = 2.0  # 이보다 큰 t_sec 점프는 녹화 중단(세그먼트 경계)로 간주

    def __init__(self, timestamp_csv: Path, segment_files: list):
        """
        timestamp_csv: (frame_idx, t_sec, t_kst, t_rel, frame_id, status) 헤더의 csv
        segment_files: [(seg_num, Path), ...] seg_num 오름차순 정렬된 리스트
        """
        self.segment_files = segment_files
        self._frame_t_sec: list[float] = self._load_timestamps(timestamp_csv)
        self._segment_row_ranges = self._compute_segment_row_ranges()  # segment_files와 1:1 대응

    def _load_timestamps(self, timestamp_csv: Path) -> list[float]:
        with open(timestamp_csv, "r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = sorted(reader, key=lambda r: int(r["frame_idx"]))
        return [float(r["t_sec"]) for r in rows]

    def _compute_segment_row_ranges(self) -> list[tuple[int, int]]:
        if not self._frame_t_sec or not self.segment_files:
            return [(0, 0) for _ in self.segment_files]

        boundaries = [0]
        for i in range(1, len(self._frame_t_sec)):
            if self._frame_t_sec[i] - self._frame_t_sec[i - 1] > self.GAP_THRESHOLD_SEC:
                boundaries.append(i)
        boundaries.append(len(self._frame_t_sec))
        detected = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]

        n = len(self.segment_files)
        if len(detected) == n:
            return detected
        elif len(detected) < n:
            # csv가 세그먼트 일부만 담고 있는 경우 - 지금까지 관측된 실제 데이터가
            # 항상 "가장 마지막" 세그먼트만 담고 있었으므로, 뒤쪽 세그먼트부터 채움
            return [(0, 0)] * (n - len(detected)) + detected
        else:
            return detected[-n:]

    def time_range_to_global_frames(self, t_start: float, t_end: float) -> tuple[int, int]:
        """절대시각 구간 -> csv 행 구간 (start 포함, end 미포함)."""
        start_idx = bisect.bisect_left(self._frame_t_sec, t_start)
        end_idx = bisect.bisect_right(self._frame_t_sec, t_end)
        return start_idx, end_idx

    def global_frames_to_file_ranges(self, start_idx: int, end_idx: int) -> list[tuple[Path, int, int]]:
        """csv 행 구간 -> [(파일경로, local_start, local_end), ...] (시간순)."""
        results = []
        for i, (_, path) in enumerate(self.segment_files):
            row_start, row_end = self._segment_row_ranges[i]
            lo = max(start_idx, row_start)
            hi = min(end_idx, row_end)
            if lo < hi:
                results.append((path, lo - row_start, hi - row_start))
        return results


class AudioTimestampIndex:
    """오디오 세그먼트(wav 여러 개) + 공유 timestamp csv -> 절대시각 매핑.

    segment_files: [(seg_num, Path), ...] seg_num 오름차순 정렬된 리스트
    """

    GAP_THRESHOLD_SEC = 2.0  # 이보다 큰 t_sec 점프는 녹화 중단(세그먼트 경계)로 간주

    def __init__(self, timestamp_csv: Path, segment_files: list):
        self.segment_files = segment_files
        self._file_info = self._probe_wave_info()  # [(framerate, nframes), ...]
        t_secs = self._load_timestamps(timestamp_csv)
        self.segment_starts = self._compute_segment_starts(t_secs)

    def _load_timestamps(self, timestamp_csv: Path) -> list[float]:
        with open(timestamp_csv, "r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = sorted(reader, key=lambda r: int(r["frame_idx"]))
        return [float(r["t_sec"]) for r in rows]

    def _probe_wave_info(self) -> list[tuple[int, int]]:
        info = []
        for _, path in self.segment_files:
            with wave.open(str(path), "rb") as wf:
                info.append((wf.getframerate(), wf.getnframes()))
        return info

    def _compute_segment_starts(self, t_secs: list[float]) -> list[float]:
        if not t_secs or not self.segment_files:
            return []

        starts = [t_secs[0]]
        for prev, cur in zip(t_secs, t_secs[1:]):
            if cur - prev > self.GAP_THRESHOLD_SEC:
                starts.append(cur)

        n = len(self.segment_files)
        if len(starts) > n:
            starts = starts[:n]
        while len(starts) < n:
            # 세그먼트 경계를 다 못 찾은 경우(csv 누락 등) 직전 세그먼트 끝에 이어붙임
            i = len(starts)
            prev_rate, prev_frames = self._file_info[i - 1]
            starts.append(starts[i - 1] + prev_frames / prev_rate)
        return starts

    def time_range_to_file_ranges(self, t_start: float, t_end: float) -> list[tuple[Path, int, int]]:
        """절대시간 구간 -> [(파일경로, local_sample_start, local_sample_end), ...] (시간순)."""
        results = []
        for i, (_, path) in enumerate(self.segment_files):
            framerate, nframes = self._file_info[i]
            seg_start = self.segment_starts[i]
            seg_end = seg_start + nframes / framerate
            lo_t = max(t_start, seg_start)
            hi_t = min(t_end, seg_end)
            if lo_t >= hi_t:
                continue
            lo = max(0, min(int(round((lo_t - seg_start) * framerate)), nframes))
            hi = max(0, min(int(round((hi_t - seg_start) * framerate)), nframes))
            if lo < hi:
                results.append((path, lo, hi))
        return results
