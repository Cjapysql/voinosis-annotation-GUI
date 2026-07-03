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
import shutil
from pathlib import Path

import cv2
import soundfile as sf

from .models import Scenario, LabelDraft
from .session_loader import TrialData, CameraStreamFiles
from .timestamp_index import CameraTimestampIndex, ChunkedTimestampIndex
from .radar_index import RadarTimestampIndex
from .video_codec import make_video_writer

ANNOTATION_CSV_FIELDS = ["segment_name", "segment_dir", "start_ts", "end_ts", "label"]


class SegmentNamer:
    """시나리오별 독립 카운터로 segment 폴더 이름 생성."""

    def __init__(self):
        self._counters = {Scenario.DISTRACTION: 0, Scenario.DROWSINESS: 0}

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
        self.namer = SegmentNamer()

        # 시나리오별 annotations csv 준비
        self.annotations_dir = self.session_dir / "annotations"
        self.annotations_dir.mkdir(parents=True, exist_ok=True)
        for scenario in Scenario:
            csv_path = self.annotations_dir / f"{scenario.value}.csv"
            if not csv_path.exists():
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(ANNOTATION_CSV_FIELDS)

        # 카메라 타임스탬프 인덱스는 스트림당 한 번만 만들면 되므로 캐시
        self._camera_index_cache: dict[tuple, CameraTimestampIndex] = {}
        self._radar_index: RadarTimestampIndex | None = None

    # ------------------------------------------------------------------
    def export_draft(self, draft: LabelDraft, cognitive_task_name: str = None) -> Path:
        segment_name = self.namer.next_name(draft.scenario, cognitive_task_name)
        segment_dir = self.session_dir / draft.scenario.value / segment_name
        for sub in ("camera", "audio", "physio_watch", "radar", "imu"):
            (segment_dir / sub).mkdir(parents=True, exist_ok=True)

        self._export_cameras(draft, segment_dir / "camera")
        self._export_audio(draft, segment_dir / "audio")
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
            }, f, ensure_ascii=False, indent=2)

        csv_path = self.annotations_dir / f"{draft.scenario.value}.csv"
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
            self._camera_index_cache[key] = CameraTimestampIndex(
                stream.timestamp_csv, stream.segment_files
            )
        return self._camera_index_cache[key]

    def _export_cameras(self, draft: LabelDraft, out_dir: Path):
        for (position, modality), stream in self.trial.cameras.items():
            if not stream.timestamp_csv or not stream.segment_files:
                continue
            index = self._get_camera_index((position, modality), stream)
            start_idx, end_idx = index.time_range_to_global_frames(draft.start_ts, draft.end_ts)
            if start_idx >= end_idx:
                continue  # 이 스트림엔 해당 구간 프레임이 없음
            file_ranges = index.global_frames_to_file_ranges(start_idx, end_idx)
            if not file_ranges:
                continue

            out_path = out_dir / f"{position}_{modality}.mp4"
            self._write_video_cut(file_ranges, out_path)

    @staticmethod
    def _write_video_cut(file_ranges: list, out_path: Path):
        writer = None
        for path, local_start, local_end in file_ranges:
            cap = cv2.VideoCapture(str(path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_idx = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if local_start <= frame_idx < local_end:
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
    def _export_audio(self, draft: LabelDraft, out_dir: Path):
        for mic_name, info in self.trial.audio.items():
            wav_path = info.get("wav")
            ts_path = info.get("timestamp_csv")
            if not wav_path or not ts_path:
                continue
            index = ChunkedTimestampIndex(ts_path)
            s0, s1 = index.time_range_to_sample_range(draft.start_ts, draft.end_ts)
            if s1 <= s0:
                continue
            with sf.SoundFile(str(wav_path)) as f:
                f.seek(s0)
                data = f.read(frames=(s1 - s0))
                out_path = out_dir / f"{mic_name}.wav"
                sf.write(str(out_path), data, f.samplerate, subtype="PCM_16")

    # ------------------------------------------------------------------
    # IMU / 워치 (timestamp 컬럼 기준 행 필터)
    # ------------------------------------------------------------------
    def _export_imu(self, draft: LabelDraft, out_dir: Path):
        for name, path in self.trial.imu.items():
            self._filter_csv_by_time(path, draft.start_ts, draft.end_ts,
                                       out_dir / f"imu_{name}.csv")

    def _export_watch(self, draft: LabelDraft, out_dir: Path):
        for name, path in self.trial.watch.items():
            self._filter_csv_by_time(path, draft.start_ts, draft.end_ts,
                                       out_dir / f"{name}.csv")

    @staticmethod
    def _filter_csv_by_time(csv_path: Path, t_start: float, t_end: float, out_path: Path,
                              ts_col_candidates=("timestamp", "t_sec")):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if not fieldnames:
                return  # 빈 파일 (헤더 없음) - 스킵
            ts_col = next((c for c in ts_col_candidates if c in fieldnames), None)
            if ts_col is None:
                # 타임스탬프 컬럼을 못 찾으면 그냥 건너뜀 (실제 컬럼명 확인 필요)
                return
            rows = [r for r in reader if t_start <= float(r[ts_col]) <= t_end]

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
