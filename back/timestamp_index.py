"""
센서별 (절대시각 <-> 프레임/샘플 위치) 매핑. t_sec를 모든 센서 공통의 정렬
축으로 삼고, 세그먼트 파일 여러 개에 걸친 프레임/샘플을 그 축 위에서 정확한
파일 하나로 되돌려 매핑하는 게 이 모듈의 역할이다.

카메라: 처음엔 "각 seg 파일의 실제 프레임 수(cv2로 조회)를 이용해 전역 frame_idx를
파일 경계로 나눈다"는 방식이었는데, 이건 timestamp csv가 정말로 모든 세그먼트에
걸쳐 빠짐없이 누적돼 있어야만 맞는 방식이었다. csv가 세그먼트 일부만 담고 있으면
(실제로 관측된 사례) "행 번호"와 "그 세그먼트 파일 안에서의 프레임 번호"가 어긋나서
엉뚱한 세그먼트 파일을 가리키는 버그가 생겼었다.

그다음엔 "csv 행 구간을 seg_num 순서대로 세그먼트 파일에 매칭"하는 방식으로
바꿨는데, 이것도 실측해보니 "csv 행 개수 = 그 세그먼트 파일의 실제 프레임 수"라는
가정이 스트림마다 최대 수백 개까지 어긋나 있었다(타임스탬프를 남기는 로거와
실제로 영상을 인코딩하는 쪽이 별개 파이프라인이라 프레임을 서로 다르게 세기
때문으로 보임). 그래서 구간 뒤쪽으로 갈수록 존재하지 않는 프레임을 요청하게
되어 멈추거나(freeze), 뒤쪽 프레임 일부가 아예 도달 불가능한 죽은 구간이 되는
문제가 있었다.

지금은 오디오와 완전히 같은 원칙으로: "행 개수 세기"를 아예 안 하고, 세그먼트의
절대 시작 시각(segment_starts, t_sec 실측값 기반) + 그 파일의 fps만으로 "절대시각
-> 로컬 프레임 인덱스"를 선형 계산한다. 그리고 이때 반올림(가장 가까운 프레임)을
쓰기 때문에, 예전처럼 "항상 요청 시각 이후의 다음 프레임만 고르는" 편향도 같이
없어진다.

fps는 cv2가 보고하는 값을 그대로 안 쓰고 보정한다 - 실측해보니 cv2는 컨테이너에
박힌 명목값(예: 정확히 30.0)을 돌려주는데, 실측 timestamp가 있는 세그먼트에서
(첫 로그~마지막 로그 사이 실제 경과 시간)과 (그 사이 진짜 프레임 수)로 역산한
평균 fps는 7개 스트림 전부 일관되게 29.3~29.4 정도였다. 이 차이를 무시하면 세그먼트
안에서 시간이 지날수록(끝쪽일수록) 최대 4~5초까지 어긋난다. 그래서 실측 있는
세그먼트는 이렇게 역산한 fps를 쓰고, 실측 없는 세그먼트(같은 카메라라 물리적으로
속도가 같다고 가정)는 그 값을 그대로 적용한다.

세그먼트별 "절대 시작 시각"(segment_starts)의 기준은 비디오다. 카메라는 프레임마다
실측 t_sec이 촘촘하게 남아서 세그먼트 경계 판단이 오디오보다 훨씬 신뢰도가 높다
(오디오는 청크 단위라 sparse함). 그래서 다른 센서(우선 오디오)는 자기 timestamp
csv만으로 독자적으로 세그먼트 시작 시각을 추정하지 말고, 가능하면 비디오 쪽에서
계산된 segment_starts를 그대로 받아써야 한다 - 각자 따로 추정하면 "csv가 세그먼트
일부만 담고 있을 때 어느 세그먼트로 볼지"를 서로 다르게 틀려서(예: 오디오는 앞쪽
세그먼트로, 비디오는 뒤쪽 세그먼트로 오인) 같은 절대시각에 서로 다른 세그먼트의
내용을 재생하는 사고가 났었다.

오디오: timestamp csv는 카메라와 유사한 스키마지만 한 행이 raw 샘플 1개가 아니라
청크(가변 길이) 이벤트라서 카메라처럼 "행 순서 = 프레임 순서"로 1:1 대응시킬 수
없음. 세그먼트 시작 절대시각만 구한 뒤 그 안에서는 표본 레이트가 일정하다는
가정으로 절대시각 -> 로컬 샘플 인덱스를 선형 계산.

컬럼 스키마: 카메라 timestamp csv는 (저장영상프레임번호, 원본센서프레임번호,
동기화기준시각_sec, ..., 복제프레임여부, 프레임종류), 오디오는 (저장오디오청크번호,
원본센서청크번호, 동기화기준시각_sec, ...). 정렬 기준 시각으로는 "저장완료시각_sec"
(디스크 저장 완료 시각, 저장지연만큼 밀림)이 아니라 "동기화기준시각_sec"(센서가
실제 캡처한 시각)을 쓴다 - 다른 센서의 t_sec과 같은 축(실제 캡처 시각)이어야
정렬이 맞기 때문. "복제프레임여부"(드라이버 지연/드롭 시 직전 프레임을 복사해
mp4 프레임 수를 채운 표시)는 무시하고 그대로 둔다 - 복제된 행은 그냥 직전 행과
동일한 시각이 한 번 더 찍히는 것뿐이라 gap 기반 세그먼트 경계 판단이나
시간->인덱스 선형 계산에 영향이 없다.

세그먼트별 timestamp csv: back/session_loader.py가 넘겨주는 segment_files는
[(seg_num, media_path, timestamp_csv_path|None), ...] 형태다. flat 구조(구
파이프라인)는 세그먼트 여러 개가 csv 하나를 공유하므로 같은 Path가 반복되고,
그 csv 안에서 GAP_THRESHOLD_SEC 이상 점프하는 지점으로 세그먼트 경계를 나눠
배분해야 한다(_split_by_gap). 신 구조(신 파이프라인)는 세그먼트 폴더 하나마다
자기 csv가 따로 있고 그 csv는 그 세그먼트 하나만의 정확한 데이터라는 게 확인돼서,
gap 감지 없이 csv 전체를 그대로 그 세그먼트 것으로 신뢰한다 - 이 두 경우를
_load_segment_t_secs()가 "같은 csv Path를 공유하는 세그먼트가 몇 개인지"로
자동 판별한다.
"""
import csv as csv_mod
import wave
from pathlib import Path

import cv2


def _load_t_sec_column(csv_path: Path, idx_col: str, t_col: str = "동기화기준시각_sec") -> list[float]:
    """timestamp csv 하나를 정렬 순번(idx_col) 기준으로 정렬해서 정렬 기준
    시각(t_col) 리스트로 반환."""
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv_mod.DictReader(f)
        rows = sorted(reader, key=lambda r: int(r[idx_col]))
    return [float(r[t_col]) for r in rows]


def _split_by_gap(t_secs: list[float], threshold: float) -> list[list[float]]:
    """t_sec 리스트를 threshold보다 크게 점프하는 지점마다 나눠 청크 리스트로 만듦
    (세그먼트 여러 개가 csv 하나를 공유하는 flat 구조에서 세그먼트 경계 판단용)."""
    if not t_secs:
        return []
    chunks = [[t_secs[0]]]
    for prev, cur in zip(t_secs, t_secs[1:]):
        if cur - prev > threshold:
            chunks.append([])
        chunks[-1].append(cur)
    return chunks


def _load_segment_t_secs(segment_files: list, idx_col: str, gap_threshold: float) -> list[list[float]]:
    """segment_files: [(seg_num, media_path, timestamp_csv_path|None), ...] ->
    세그먼트별 t_sec 리스트(segment_files와 같은 길이의 병렬 리스트, 세그먼트별로
    csv가 없거나 데이터가 없으면 빈 리스트). 같은 csv Path를 공유하는 세그먼트가
    여럿이면(flat 구조) 그 csv 안에서 gap 감지로 나눠 배분하고, csv를 혼자 쓰는
    세그먼트는(신 구조) 그 csv 전체를 그대로 그 세그먼트 것으로 삼는다."""
    n = len(segment_files)
    result: list[list[float]] = [[] for _ in range(n)]

    groups: dict[Path, list[int]] = {}
    for i, (_seg_num, _media_path, ts_path) in enumerate(segment_files):
        if ts_path is None:
            continue
        groups.setdefault(ts_path, []).append(i)

    for ts_path, indices in groups.items():
        t_secs = _load_t_sec_column(ts_path, idx_col)
        if len(indices) == 1:
            result[indices[0]] = t_secs
            continue

        chunks = _split_by_gap(t_secs, gap_threshold)
        m = len(indices)
        if len(chunks) < m:
            # csv가 세그먼트 일부만 담고 있는 경우 - 지금까지 관측된 실제 데이터가
            # 항상 "가장 마지막" 세그먼트만 담고 있었으므로, 뒤쪽 세그먼트부터 채움
            chunks = [[] for _ in range(m - len(chunks))] + chunks
        elif len(chunks) > m:
            chunks = chunks[-m:]
        for idx, chunk in zip(indices, chunks):
            result[idx] = chunk

    return result


def _fill_segment_starts(anchors: list, durations: list[float]) -> list:
    """실측으로 얻은 세그먼트별 시작 시각(anchors[i], 없으면 None)을 이웃 세그먼트의
    시작 시각 + 자기 길이(durations)로 앞/뒤로 이어붙여 역산해서 채운다. 이웃도
    실측이 없어서 못 채운 자리는 None으로 그대로 남는다."""
    n = len(anchors)
    starts = list(anchors)
    for i in range(n - 2, -1, -1):  # 뒤에서 앞으로: 다음 세그먼트 시작 - 자기 길이
        if starts[i] is None and starts[i + 1] is not None:
            starts[i] = starts[i + 1] - durations[i]
    for i in range(1, n):  # 앞에서 뒤로: 이전 세그먼트 시작 + 이전 길이
        if starts[i] is None and starts[i - 1] is not None:
            starts[i] = starts[i - 1] + durations[i - 1]
    return starts


class CameraTimestampIndex:
    GAP_THRESHOLD_SEC = 2.0  # 이보다 큰 t_sec 점프는 녹화 중단(세그먼트 경계)로 간주
    _IDX_COLUMN = "저장영상프레임번호"

    def __init__(self, segment_files: list):
        """
        segment_files: [(seg_num, media_path, timestamp_csv_path|None), ...]
        seg_num 오름차순 정렬된 리스트. timestamp_csv_path는 세그먼트 여러 개가
        공유할 수도(flat 구조), 세그먼트 하나만의 것일 수도 있다(신 구조).
        """
        self.segment_files = [(seg_num, path) for seg_num, path, _ts in segment_files]
        self._segment_t_secs: list[list[float]] = _load_segment_t_secs(
            segment_files, self._IDX_COLUMN, self.GAP_THRESHOLD_SEC
        )
        # (프레임 수, cv2가 보고하는 명목 fps) - csv와는 무관하게 파일 자체에서 직접 읽음
        self._segment_info: list[tuple[int, float]] = self._probe_segment_info()
        # 실측 기반으로 보정한 fps - 프레임 위치 계산은 전부 이 값을 씀 (cv2 fps 안 씀)
        self._segment_fps: list[float] = self._calibrate_fps()
        # 세그먼트별 절대 시작 시각 - 다른 센서(오디오 등)가 자기 세그먼트를
        # 맞출 때 이 값을 기준(reference)으로 그대로 받아쓸 수 있게 공개해둠
        self.segment_starts: list[float] = self._compute_segment_starts()

    def _probe_segment_info(self) -> list[tuple[int, float]]:
        info = []
        for _, path in self.segment_files:
            cap = cv2.VideoCapture(str(path))
            nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.release()
            info.append((nframes, fps))
        return info

    def _calibrate_fps(self) -> list[float]:
        """cv2가 보고하는 fps(명목값)를 실측 timestamp 기반으로 보정.
        실측 있는 세그먼트: (첫 로그~마지막 로그 실제 경과 시간)과 (그 사이 진짜
        프레임 수)로 직접 역산. 실측 없는 세그먼트: 같은 카메라이므로 물리적으로
        같은 속도라고 보고, 실측 있는 세그먼트의 보정값을 그대로 적용."""
        calibrated: list = [None] * len(self.segment_files)
        for i, t_secs in enumerate(self._segment_t_secs):
            if len(t_secs) < 2:
                continue
            nframes, _cv2_fps = self._segment_info[i]
            if nframes <= 1:
                continue
            real_span = t_secs[-1] - t_secs[0]
            if real_span > 0:
                calibrated[i] = (nframes - 1) / real_span

        known = [c for c in calibrated if c is not None]
        fallback = sum(known) / len(known) if known else None

        result = []
        for i, (_nframes, cv2_fps) in enumerate(self._segment_info):
            if calibrated[i] is not None:
                result.append(calibrated[i])
            elif fallback is not None:
                result.append(fallback)
            else:
                result.append(cv2_fps)
        return result

    def _compute_segment_starts(self) -> list[float]:
        """세그먼트별 절대 시작 시각. 실측 데이터가 있는 세그먼트는 그 첫 t_sec을
        그대로 쓰고, 없는 세그먼트는 이웃(실측 있는) 세그먼트의 시각에서 각 파일
        자체의 길이(보정된 fps 기준)만큼 앞/뒤로 이어붙여서 역산한다."""
        anchors = [t_secs[0] if t_secs else None for t_secs in self._segment_t_secs]
        if all(a is None for a in anchors):
            return []

        durations = [nframes / self._segment_fps[i] for i, (nframes, _fps) in enumerate(self._segment_info)]
        starts = _fill_segment_starts(anchors, durations)
        return [] if any(s is None for s in starts) else starts

    @property
    def first_t_sec(self) -> float | None:
        """이 스트림 전체에서 가장 이른 절대 시각 (타임라인 전체 범위 계산용)."""
        return self.segment_starts[0] if self.segment_starts else None

    @property
    def last_t_sec(self) -> float | None:
        """이 스트림 전체에서 가장 늦은 절대 시각 (타임라인 전체 범위 계산용)."""
        if not self.segment_starts:
            return None
        bounds = self._segment_bounds(len(self.segment_starts) - 1)
        return bounds[1] if bounds else None

    def segment_coverage(self) -> list[tuple[float, float]]:
        """세그먼트별 (절대 시작, 절대 끝) 리스트. first_t_sec/last_t_sec가
        스트림 전체를 하나의 범위로 뭉치는 것과 달리, 세그먼트 사이의 실제
        녹화 공백을 그대로 드러낸다 - back/coverage.py가 다른 센서에 대해
        만드는 것과 같은 형태라 range_overlaps_any()로 바로 겹침 확인 가능."""
        bounds = (self._segment_bounds(i) for i in range(len(self.segment_starts)))
        return [b for b in bounds if b is not None]

    def _segment_bounds(self, i: int) -> tuple[float, float] | None:
        """세그먼트 i의 (절대 시작, 절대 끝) 시각. segment_starts를 못 구했으면 None."""
        if i >= len(self.segment_starts):
            return None
        nframes, _cv2_fps = self._segment_info[i]
        fps = self._segment_fps[i]
        if nframes <= 0 or fps <= 0:
            return None
        start = self.segment_starts[i]
        return start, start + nframes / fps

    def frame_at_time(self, t: float) -> tuple[Path, int] | None:
        """절대시각 t에 가장 가까운 (파일 경로, 로컬 프레임 인덱스).
        t가 모든 세그먼트 범위 밖이면 가장 가까운 세그먼트의 처음/끝 프레임으로 클램프."""
        if not self.segment_starts:
            return None
        best = None  # (밖으로 벗어난 거리, path, local_idx) - 범위 안이면 거리 0으로 즉시 반환
        for i, (_, path) in enumerate(self.segment_files):
            bounds = self._segment_bounds(i)
            if bounds is None:
                continue
            start, end = bounds
            nframes, _cv2_fps = self._segment_info[i]
            fps = self._segment_fps[i]
            if start <= t < end:
                local_idx = int(round((t - start) * fps))
                local_idx = max(0, min(local_idx, nframes - 1))
                return path, local_idx
            dist = (start - t) if t < start else (t - end)
            if best is None or dist < best[0]:
                clamped_idx = 0 if t < start else nframes - 1
                best = (dist, path, clamped_idx)
        return (best[1], best[2]) if best is not None else None

    def time_range_to_file_ranges(self, t_start: float, t_end: float) -> list[tuple[Path, int, int, float, float, float]]:
        """절대시간 구간 -> [(파일경로, local_start, local_end, 이 조각의 절대시작,
        절대끝, 이 세그먼트의 보정된 fps), ...] (시간순). export용. 절대시작/끝과
        fps는 요청 구간이 이 스트림의 세그먼트 사이 공백에 걸칠 때(경계 프레임을
        반복해서 채움, back/segment_exporter.py) 필요하다."""
        results = []
        for i, (_, path) in enumerate(self.segment_files):
            bounds = self._segment_bounds(i)
            if bounds is None:
                continue
            start, end = bounds
            nframes, _cv2_fps = self._segment_info[i]
            fps = self._segment_fps[i]
            lo_t = max(t_start, start)
            hi_t = min(t_end, end)
            if lo_t >= hi_t:
                continue
            lo = max(0, min(int(round((lo_t - start) * fps)), nframes))
            hi = max(0, min(int(round((hi_t - start) * fps)), nframes))
            if lo < hi:
                results.append((path, lo, hi, start + lo / fps, start + hi / fps, fps))
        return results


class AudioTimestampIndex:
    """오디오 세그먼트(wav 여러 개) + 세그먼트별 timestamp csv -> 절대시각 매핑.

    segment_files: [(seg_num, media_path, timestamp_csv_path|None), ...] seg_num 오름차순 정렬
    """

    GAP_THRESHOLD_SEC = 2.0  # 이보다 큰 t_sec 점프는 녹화 중단(세그먼트 경계)로 간주
    _IDX_COLUMN = "저장오디오청크번호"

    def __init__(self, segment_files: list, reference_segment_starts=None):
        """오디오도 카메라와 동일하게, 자기 세그먼트별 timestamp csv로 먼저 스스로
        segment_starts를 계산한다(세그먼트 폴더 하나당 자기 csv가 정확하다는 게
        확인됨 - 더 이상 비디오 뒤에 숨어서 안 읽을 이유가 없음).

        reference_segment_starts: list[float] 또는 () -> list[float]|None 콜러블.
        자기 데이터로 도저히 못 채운 세그먼트가 있을 때만(자기 csv가 없거나
        비어있고, 이웃 세그먼트로도 역산이 안 되는 경우) 그 세그먼트에 한해서만
        보조로 채워넣는다 - 전체를 통째로 대체하지 않는다. 콜러블로 넘기면
        자기 데이터로 이미 다 채워진 경우(대부분) 아예 평가되지 않는다 - 비디오
        세그먼트 인덱스를 새로 만드는 건 대용량 csv 파싱 등으로 비용이 커서,
        실제로 필요할 때만 계산하게 하려는 것 (export 시 매번 무조건 계산했다가
        몇 초~수십 초씩 멈춰서 최종 저장이 안 끝나던 문제가 있었음)."""
        self.segment_files = [(seg_num, path) for seg_num, path, _ts in segment_files]
        self._file_info = self._probe_wave_info()  # [(framerate, nframes), ...]

        segment_t_secs = _load_segment_t_secs(segment_files, self._IDX_COLUMN, self.GAP_THRESHOLD_SEC)
        anchors = [t_secs[0] if t_secs else None for t_secs in segment_t_secs]
        durations = [nframes / rate for rate, nframes in self._file_info]
        starts = _fill_segment_starts(anchors, durations)

        if any(s is None for s in starts) and reference_segment_starts is not None:
            ref = reference_segment_starts() if callable(reference_segment_starts) else reference_segment_starts
            if ref is not None and len(ref) == len(segment_files):
                starts = [s if s is not None else r for s, r in zip(starts, ref)]

        self.segment_starts = [] if any(s is None for s in starts) else starts

    def _probe_wave_info(self) -> list[tuple[int, int]]:
        info = []
        for _, path in self.segment_files:
            with wave.open(str(path), "rb") as wf:
                info.append((wf.getframerate(), wf.getnframes()))
        return info

    def time_range_to_file_ranges(self, t_start: float, t_end: float) -> list[tuple[Path, int, int, float, float, int]]:
        """절대시간 구간 -> [(파일경로, local_sample_start, local_sample_end, 이
        조각의 절대시작, 절대끝, 샘플레이트), ...] (시간순). 절대시작/끝은 요청
        구간이 세그먼트 사이 공백에 걸칠 때 무음을 얼마나 채울지 계산하는 데
        필요하다(back/segment_exporter.py)."""
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
                results.append((path, lo, hi, seg_start + lo / framerate, seg_start + hi / framerate, framerate))
        return results