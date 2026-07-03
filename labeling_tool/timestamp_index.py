"""
스트림별 (절대시각 <-> 프레임/샘플 위치) 매핑.

카메라: timestamp csv의 frame_idx가 여러 seg mp4 파일에 걸쳐 연속 누적된다는
가정 하에, 각 seg 파일의 실제 프레임 수(cv2로 조회)를 이용해 전역 frame_idx를
(파일, 파일 내 local frame_idx)로 되돌려 매핑.

오디오: timestamp csv가 청크 단위(chunk_idx, timestamp, num_samples)이므로
누적 샘플 오프셋을 계산해서 절대시각 -> 샘플 인덱스로 변환.
"""
import bisect
import csv as csv_mod
from pathlib import Path

import cv2


class CameraTimestampIndex:
    def __init__(self, timestamp_csv: Path, segment_files: list):
        """
        timestamp_csv: (frame_idx, t_sec, t_kst, t_rel, frame_id, status) 헤더의 csv
        segment_files: [(seg_num, Path), ...] seg_num 오름차순 정렬된 리스트
        """
        self.segment_files = segment_files
        self._frame_t_sec: list[float] = []   # 전역 frame_idx(0-base) -> t_sec
        self._load_timestamps(timestamp_csv)
        self._file_frame_counts = self._probe_frame_counts()
        self._cum_counts = self._cumulative(self._file_frame_counts)

    def _load_timestamps(self, timestamp_csv: Path):
        with open(timestamp_csv, "r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = sorted(reader, key=lambda r: int(r["frame_idx"]))
        self._frame_t_sec = [float(r["t_sec"]) for r in rows]

    def _probe_frame_counts(self) -> list[int]:
        counts = []
        for _, path in self.segment_files:
            cap = cv2.VideoCapture(str(path))
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            counts.append(count)
        return counts

    @staticmethod
    def _cumulative(counts: list[int]) -> list[int]:
        cum = []
        total = 0
        for c in counts:
            cum.append(total)
            total += c
        cum.append(total)  # 마지막에 총합 추가 (상한 경계용)
        return cum

    def time_range_to_global_frames(self, t_start: float, t_end: float) -> tuple[int, int]:
        """절대시각 구간 -> 전역 frame_idx 구간 (start 포함, end 미포함)."""
        start_idx = bisect.bisect_left(self._frame_t_sec, t_start)
        end_idx = bisect.bisect_right(self._frame_t_sec, t_end)
        return start_idx, end_idx

    def global_frames_to_file_ranges(self, start_idx: int, end_idx: int) -> list[tuple[Path, int, int]]:
        """전역 frame 구간 -> [(파일경로, local_start, local_end), ...] (시간순)."""
        results = []
        for i, (_, path) in enumerate(self.segment_files):
            file_start = self._cum_counts[i]
            file_end = self._cum_counts[i + 1]
            lo = max(start_idx, file_start)
            hi = min(end_idx, file_end)
            if lo < hi:
                results.append((path, lo - file_start, hi - file_start))
        return results


class ChunkedTimestampIndex:
    """오디오처럼 (chunk_idx, timestamp, num_samples) 형태인 스트림용."""

    def __init__(self, timestamp_csv: Path):
        self._chunks = []  # [(t_sec, cumulative_sample_start, num_samples)]
        cum = 0
        with open(timestamp_csv, "r", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = sorted(reader, key=lambda r: int(r["chunk_idx"]))
        for r in rows:
            n = int(r["num_samples"])
            self._chunks.append((float(r["timestamp"]), cum, n))
            cum += n
        self._t_secs = [c[0] for c in self._chunks]

    def time_to_sample_index(self, t: float) -> int:
        idx = bisect.bisect_left(self._t_secs, t)
        idx = min(idx, len(self._chunks) - 1) if self._chunks else 0
        if not self._chunks:
            return 0
        return self._chunks[idx][1]

    def time_range_to_sample_range(self, t_start: float, t_end: float) -> tuple[int, int]:
        return self.time_to_sample_index(t_start), self.time_to_sample_index(t_end)
