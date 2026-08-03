"""
확정된 LabelDraft를 받아서:
  1. 절대시간(start_ts~end_ts) 기준으로 모든 센서 데이터를 프레임/샘플 정확도로 자르고
  2. session_XXX_id_XXX/{scenario}/{segment_name}/ 구조로 저장
  3. annotation.json 저장 + annotations/{scenario}.csv에 한 줄 추가

비디오는 프레임 단위 정확도가 필요하다고 확인되어(재인코딩 방식),
OpenCV로 프레임을 순차 디코딩하면서 target 구간만 다시 인코딩합니다.
(ffmpeg -ss 키프레임 탐색 방식은 오차가 생길 수 있어 사용하지 않음)
"""
import csv
import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf

from .models import Scenario, LabelDraft, TaskWindow
from .session_loader import TrialData, CameraStreamFiles, AudioStreamFiles
from .timestamp_index import CameraTimestampIndex, AudioTimestampIndex
from .radar_index import RadarTimestampIndex
from .video_codec import make_video_writer

ANNOTATION_CSV_FIELDS = ["segment_name", "segment_dir", "start_ts", "end_ts", "label"]

# 오디오 세그먼트 경계 판단 기준으로 쓸 비디오 스트림 우선순위 (front/labeling_page.py의
# DISPLAY_STREAMS 우선순위와 동일 원칙 - driver_rgb를 최우선으로 고정)
_CAMERA_REFERENCE_PRIORITY = [
    ("driver", "rgb"), ("behavior", "rgb"), ("road", "rgb"),
    ("driver", "infrared"), ("behavior", "infrared"), ("road", "infrared"),
]


class SegmentNamer:
    """시나리오별 독립 카운터로 segment 폴더 이름 생성.

    라벨링을 하다가 앱을 껐다가 나중에 같은 트라이얼을 다시 열어서 이어서 하는
    경우, 카운터가 그냥 0부터 다시 시작하면 이전에 저장해둔 segment001을 새
    segment001이 조용히 덮어쓰는 사고가 난다. 그래서 session_dir에 이미 있는
    segment 폴더를 스캔해서, 그 중 가장 큰 번호부터 이어간다."""

    def __init__(self, session_dir: Path = None):
        self._counters = {Scenario.DISTRACTION: 0, Scenario.DROWSINESS: 0}
        if session_dir is not None:
            session_dir = Path(session_dir)
            for scenario in self._counters:
                scenario_dir = session_dir / scenario.value
                if not scenario_dir.exists():
                    continue
                pattern = re.compile(rf"^{re.escape(scenario.value)}_segment(\d+)$")
                max_num = 0
                for p in scenario_dir.iterdir():
                    if not p.is_dir():
                        continue
                    m = pattern.match(p.name)
                    if m:
                        max_num = max(max_num, int(m.group(1)))
                self._counters[scenario] = max_num

    def next_name(self, scenario: Scenario, cognitive_task_name: str = None) -> str:
        if scenario == Scenario.COGNITIVE:
            if not cognitive_task_name:
                raise ValueError("cognitive segment는 task_name(예: pre_nback1)이 필요합니다.")
            return cognitive_task_name
        self._counters[scenario] += 1
        return f"{scenario.value}_segment{self._counters[scenario]:03d}"


class SegmentExporter:
    def __init__(self, trial: TrialData, session_dir: Path):
        self.trial = trial
        self.session_dir = Path(session_dir)
        self.namer = SegmentNamer(self.session_dir)

        # 시나리오별 annotations csv 준비
        self.annotations_dir = self.session_dir / "annotations"
        self.annotations_dir.mkdir(parents=True, exist_ok=True)
        for scenario in Scenario:
            csv_path = self.annotations_dir / f"{scenario.value}.csv"
            if not csv_path.exists():
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(ANNOTATION_CSV_FIELDS)

        # 카메라/오디오 타임스탬프 인덱스는 스트림당 한 번만 만들면 되므로 캐시
        self._camera_index_cache: dict[tuple, CameraTimestampIndex] = {}
        self._audio_index_cache: dict[str, AudioTimestampIndex] = {}
        self._radar_index: RadarTimestampIndex | None = None

        # _write_video_cut이 빠른 탐색(cap.set) 대신 안전한 순차 디코딩으로
        # 폴백한 경우를 기록 - front/에서 커밋 끝난 뒤 라벨러에게 알려주는 용도.
        # export_draft를 호출하는 쪽(front/)이 배치 시작 전 비워두고 끝난 뒤 확인.
        self.export_warnings: list[str] = []

    # ------------------------------------------------------------------
    def export_draft(self, draft: LabelDraft, cognitive_task_name: str = None,
                      source_window: TaskWindow = None, on_progress=None) -> Path:
        """on_progress: 선택적 콜백 (str) -> None. 카메라 재인코딩이 스트림당
        수 초~수십 초 걸릴 수 있어서(back/segment_exporter.py 주석 참고), 어떤
        스트림을 내보내는 중인지 문자열로 알려준다 - Qt에 의존하면 안 되는
        계층이라 시그널 대신 평범한 콜러블로 받는다(front/의 ExportWorker가
        Qt 시그널로 다시 감싸서 전달)."""
        segment_name = self.namer.next_name(draft.scenario, cognitive_task_name)
        segment_dir = self.session_dir / draft.scenario.value / segment_name
        for sub in ("camera", "audio", "physio_watch", "radar", "imu"):
            (segment_dir / sub).mkdir(parents=True, exist_ok=True)

        self._export_cameras(draft, segment_dir / "camera", on_progress)
        if on_progress:
            on_progress("오디오 내보내는 중...")
        self._export_audio(draft, segment_dir / "audio")
        if on_progress:
            on_progress("IMU/워치/레이더 내보내는 중...")
        self._export_imu(draft, segment_dir / "imu")
        self._export_watch(draft, segment_dir / "physio_watch")
        self._export_radar(draft, segment_dir / "radar")

        with open(segment_dir / "annotation.json", "w", encoding="utf-8") as f:
            json.dump({
                "scenario": draft.scenario.value,
                "start_ts": draft.start_ts,
                "end_ts": draft.end_ts,
                "source_window_id": draft.source_window_id,
                "label_fields": draft.label_fields,
                "is_free_text_override": draft.is_free_text_override,
                # survey json 원본 필드(cognitive의 NASA-TLX/SAM/KSS, driving의
                # distraction_area/kss_score 등) 보존 - 라벨러가 입력한 label_fields와는
                # 별개로, 원 설문 응답을 그대로 남겨서 나중에 참고할 수 있게 함.
                "survey_extra": source_window.extra if source_window is not None else {},
            }, f, ensure_ascii=False, indent=2)

        # annotations 폴더는 __init__ 시점에 한 번만 만들어지는데, 그 뒤에
        # (수동 삭제 등으로) 사라지면 세그먼트 파일은 전부 정상적으로 다 쓰고도
        # 마지막 이 한 줄 때문에 export 전체가 실패한 것처럼 보이는 문제가
        # 있었음 - 매번 다시 보장해서 그런 일이 없게 한다.
        self.annotations_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.annotations_dir / f"{draft.scenario.value}.csv"
        if not csv_path.exists():
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(ANNOTATION_CSV_FIELDS)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                segment_name, str(segment_dir), draft.start_ts, draft.end_ts,
                json.dumps(draft.label_fields, ensure_ascii=False),
            ])

        return segment_dir

    # ------------------------------------------------------------------
    # 카메라
    # ------------------------------------------------------------------
    def _get_camera_index(self, key, stream: CameraStreamFiles) -> CameraTimestampIndex:
        if key not in self._camera_index_cache:
            self._camera_index_cache[key] = CameraTimestampIndex(stream.segment_files)
        return self._camera_index_cache[key]

    def _export_cameras(self, draft: LabelDraft, out_dir: Path, on_progress=None):
        streams = [(k, s) for k, s in self.trial.cameras.items() if s.segment_files]
        for i, ((position, modality), stream) in enumerate(streams):
            if on_progress:
                on_progress(f"카메라 내보내는 중: {position}_{modality} ({i + 1}/{len(streams)})")
            index = self._get_camera_index((position, modality), stream)
            file_ranges = index.time_range_to_file_ranges(draft.start_ts, draft.end_ts)
            if not file_ranges:
                continue  # 이 스트림엔 해당 구간 프레임이 없음

            out_path = out_dir / f"{position}_{modality}.mp4"
            # road 카메라는 광축 기준 180도 돌아간 채 장착되어 있어서 저장 전에 보정
            self._write_video_cut(file_ranges, out_path, stream_label=f"{position}_{modality}",
                                   flip_180=(position == "road"))

    def _write_video_cut(self, file_ranges: list, out_path: Path, stream_label: str, flip_180: bool = False):
        writer = None
        for path, local_start, local_end in file_ranges:
            cap = cv2.VideoCapture(str(path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

            # local_start까지 프레임 0부터 전부 디코딩하면(구 방식) 긴 세그먼트
            # 파일 뒤쪽 구간을 자를 때 매우 느림(실측: 14만 프레임짜리 세그먼트
            # 중 5천 프레임 지점까지만 가는데도 스트림 하나당 수 초~수십 초,
            # 전체 export가 1분 가까이 걸려 OS가 "응답 없음"을 띄울 정도였음).
            # cap.set()으로 가까이 탐색한 뒤 실제 도달한 위치를 확인하고 모자란
            # 만큼만 순차 디코딩으로 보정한다 - 이 프로젝트가 쓰는 mp4v 코덱에서
            # 요청한 프레임에 정확히 도달하는 것을 실측으로 확인함(픽셀 단위로
            # 완전히 동일). 혹시 다른 파일/코덱에서 탐색이 요청 지점을 넘어서
            # 버리면(정확도가 깨질 수 있는 상황) 안전하게 프레임 0부터 다시
            # 순차 디코딩하는 기존 방식으로 폴백하고, 그 사실을 기록해둔다.
            frame_idx = 0
            if local_start > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, local_start)
                landed = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                if 0 <= landed <= local_start:
                    frame_idx = landed
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    frame_idx = 0
                    self.export_warnings.append(
                        f"{stream_label} ({path.name}): 프레임 탐색이 예상과 달라(요청={local_start}, "
                        f"도달={landed}) 순차 디코딩으로 대체했습니다 - 정확도는 유지되지만 느렸을 수 있습니다."
                    )

            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if local_start <= frame_idx < local_end:
                    if flip_180:
                        frame = cv2.rotate(frame, cv2.ROTATE_180)
                    if writer is None:
                        h, w = frame.shape[:2]
                        writer = make_video_writer(out_path, fps, (w, h))
                    writer.write(frame)
                frame_idx += 1
                if frame_idx >= local_end:
                    break
            cap.release()
        if writer is not None:
            writer.release()

    # ------------------------------------------------------------------
    # 오디오
    # ------------------------------------------------------------------
    def _get_audio_index(self, mic_name: str, stream: AudioStreamFiles,
                          reference_segment_starts) -> AudioTimestampIndex:
        if mic_name not in self._audio_index_cache:
            self._audio_index_cache[mic_name] = AudioTimestampIndex(
                stream.segment_files, reference_segment_starts=reference_segment_starts
            )
        return self._audio_index_cache[mic_name]

    def _reference_camera_segment_starts(self, expected_count: int) -> list[float] | None:
        """오디오 세그먼트 경계 판단의 기준으로 삼을 비디오 세그먼트 시작 시각.
        front/labeling_page.py의 동일 원칙 - 카메라마다 fps 미세 오차가 있어서
        매번 다른 스트림을 기준으로 쓰면 안 되므로 고정 우선순위로 고른다
        (오디오 자체 csv만으로 세그먼트를 추정하면 엉뚱한 세그먼트로 오인하는
        사고가 났던 전례가 있어, export 시에도 반드시 비디오 기준을 넘겨야 한다)."""
        for key in _CAMERA_REFERENCE_PRIORITY:
            stream = self.trial.cameras.get(key)
            if stream is None or not stream.segment_files:
                continue
            starts = self._get_camera_index(key, stream).segment_starts
            if starts and len(starts) == expected_count:
                return starts
        return None

    def _export_audio(self, draft: LabelDraft, out_dir: Path):
        for mic_name, stream in self.trial.audio.items():
            if not stream.segment_files:
                continue
            # 콜러블로 넘겨서, 오디오가 자기 데이터로 이미 다 채워지는 보통의
            # 경우엔 이 무거운 계산(카메라 스트림마다 대용량 csv 파싱)이 아예
            # 실행되지 않게 한다 (AudioTimestampIndex 쪽에서 필요할 때만 호출).
            reference_starts = lambda n=len(stream.segment_files): self._reference_camera_segment_starts(n)
            index = self._get_audio_index(mic_name, stream, reference_starts)
            file_ranges = index.time_range_to_file_ranges(draft.start_ts, draft.end_ts)
            if not file_ranges:
                continue  # 이 마이크엔 해당 구간 오디오가 없음(세그먼트 사이 gap 등)

            chunks = []
            samplerate = None
            for path, s0, s1 in file_ranges:
                with sf.SoundFile(str(path)) as f:
                    f.seek(s0)
                    chunks.append(f.read(frames=(s1 - s0)))
                    samplerate = f.samplerate
            if not chunks:
                continue

            data = np.concatenate(chunks)
            out_path = out_dir / f"{mic_name}.wav"
            sf.write(str(out_path), data, samplerate, subtype="PCM_16")

    # ------------------------------------------------------------------
    # IMU / 워치 (timestamp 컬럼 기준 행 필터)
    # ------------------------------------------------------------------
    def _export_imu(self, draft: LabelDraft, out_dir: Path):
        for name, paths in self.trial.imu.items():
            self._filter_csv_by_time(paths, draft.start_ts, draft.end_ts,
                                       out_dir / f"imu_{name}.csv")

    def _export_watch(self, draft: LabelDraft, out_dir: Path):
        for name, paths in self.trial.watch.items():
            self._filter_csv_by_time(paths, draft.start_ts, draft.end_ts,
                                       out_dir / f"{name}.csv")

    @staticmethod
    def _filter_csv_by_time(csv_paths: list, t_start: float, t_end: float, out_path: Path,
                              ts_col_candidates=("timestamp", "t_sec")):
        """csv_paths: 같은 센서의 세그먼트별 csv 파일 목록 (녹화가 중단 없이 1개면
        원소 1개). 라벨 구간이 세그먼트 경계에 걸쳐 있을 수도 있으므로, 전부 열어서
        t_start~t_end 안에 드는 행을 순서대로 모아 하나의 csv로 합친다 - 한 파일만
        보면 그 구간이 다른 세그먼트에 있을 때 조용히 빈 결과가 나가는 문제가 있었음."""
        fieldnames = None
        rows = []
        for csv_path in csv_paths:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                file_fieldnames = reader.fieldnames
                if not file_fieldnames:
                    continue  # 빈 파일 (헤더 없음) - 스킵
                if fieldnames is None:
                    fieldnames = file_fieldnames
                ts_col = next((c for c in ts_col_candidates if c in file_fieldnames), None)
                if ts_col is None:
                    # 타임스탬프 컬럼을 못 찾으면 이 파일만 건너뜀 (실제 컬럼명 확인 필요)
                    continue
                rows.extend(r for r in reader if t_start <= float(r[ts_col]) <= t_end)

        if fieldnames is None:
            return  # 유효한 csv가 하나도 없었음

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    # ------------------------------------------------------------------
    # 레이더
    # ------------------------------------------------------------------
    def _get_radar_index(self) -> RadarTimestampIndex | None:
        raw_dir = self.trial.radar.get("raw_dir")
        if raw_dir is None:
            return None
        if self._radar_index is None:
            self._radar_index = RadarTimestampIndex(raw_dir)
        return self._radar_index

    def _export_radar(self, draft: LabelDraft, out_dir: Path):
        index = self._get_radar_index()
        if index is None:
            return
        frames = index.time_range_to_frames(draft.start_ts, draft.end_ts)
        if not frames:
            return

        out_bin_path = out_dir / "radar_raw.bin"
        out_csv_path = out_dir / "radar_frame_index.csv"

        bin_handles: dict[Path, object] = {}
        used_cfgs: dict[str, Path] = {}  # sha256 -> cfg_path (중복 제거)

        try:
            with open(out_bin_path, "wb") as out_bin, \
                 open(out_csv_path, "w", newline="", encoding="utf-8") as out_csv:
                writer = csv.writer(out_csv)
                writer.writerow(["frame_idx", "t_sec", "offset_int16_before",
                                  "num_int16", "shape_chirps_rx_adc"])

                new_offset_int16 = 0
                for new_idx, fr in enumerate(frames):
                    if fr.bin_path not in bin_handles:
                        bin_handles[fr.bin_path] = open(fr.bin_path, "rb")
                    src = bin_handles[fr.bin_path]
                    src.seek(fr.offset_int16_before * 2)
                    data = src.read(fr.num_int16 * 2)
                    out_bin.write(data)

                    writer.writerow([new_idx, fr.t_sec, new_offset_int16,
                                      fr.num_int16, fr.shape])
                    new_offset_int16 += fr.num_int16

                    if fr.cfg_path is not None and fr.cfg_sha256:
                        used_cfgs.setdefault(fr.cfg_sha256, fr.cfg_path)
        finally:
            for f in bin_handles.values():
                f.close()

        # 사용된 cfg 전부 보존 (구간 중간에 설정이 바뀐 경우 여러 개일 수 있음)
        if len(used_cfgs) == 1:
            (sha, cfg_path), = used_cfgs.items()
            shutil.copy(cfg_path, out_dir / "used_cfg.cfg")
            (out_dir / "used_cfg_sha256.txt").write_text(f"{sha}  used_cfg.cfg\n", encoding="utf-8")
        else:
            for i, (sha, cfg_path) in enumerate(used_cfgs.items()):
                shutil.copy(cfg_path, out_dir / f"used_cfg_{i}.cfg")
                (out_dir / f"used_cfg_{i}_sha256.txt").write_text(
                    f"{sha}  used_cfg_{i}.cfg\n", encoding="utf-8")
