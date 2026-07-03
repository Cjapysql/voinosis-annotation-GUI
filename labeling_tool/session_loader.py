"""
원본 수집 데이터 폴더 (예: D:\\bags\\id12345_trial2_20260615_152028_승우) 탐색.

카메라 파일명 규칙 (실제 관측 예시 기준):
  {raw_position}_{raw_modality}_seg{NNN}.mp4
  예: front_depth_seg001.mp4, behavior_color_seg006.mp4, road_infrared_seg003.mp4

  raw_position: front | behavior | road   -> 최종 저장 시 driver | behavior | road로 정규화
  raw_modality: color | infrared | depth  -> 최종 저장 시 rgb | infrared | depth로 정규화

  seg 번호는 녹화가 중단되었다가 재시작될 때마다 붙는 것으로 보이며,
  번호가 연속이 아닐 수 있음(001, 003, 006 등) -> 정렬만 하고 값 자체는 신뢰하지 않음.

  timestamp csv는 세그먼트별이 아니라 스트림 전체에 대해 1개
  ({raw_position}_{raw_modality}_timestamps.csv)이며 frame_idx가
  전체 세그먼트에 걸쳐 연속으로 누적된다고 가정 (behavior_color_timestamps.csv
  실측 샘플 기준). 이 가정이 틀리면 TimestampIndex 쪽만 수정하면 됨.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

CAMERA_POSITION_ALIASES = {"front": "driver", "behavior": "behavior", "road": "road"}
CAMERA_MODALITY_ALIASES = {"color": "rgb", "infrared": "infrared", "depth": "depth"}

_CAMERA_FILE_RE = re.compile(
    r"^(?P<position>\w+?)_(?P<modality>color|infrared|depth)_seg(?P<seg>\d+)\.mp4$"
)


@dataclass
class CameraStreamFiles:
    position: str          # 정규화된 이름: driver | behavior | road
    modality: str          # 정규화된 이름: rgb | infrared | depth
    segment_files: list = field(default_factory=list)  # [(seg_num, Path)], seg 번호 오름차순 정렬됨
    timestamp_csv: Path = None


@dataclass
class TrialData:
    trial_dir: Path
    cameras: dict = field(default_factory=dict)   # (position, modality) -> CameraStreamFiles
    audio: dict = field(default_factory=dict)      # mic_name -> {"wav": Path, "timestamp_csv": Path}
    imu: dict = field(default_factory=dict)        # "accel"/"gyro" -> Path
    radar: dict = field(default_factory=dict)      # "raw_bin"/"timestamp_csv" -> Path
    watch: dict = field(default_factory=dict)      # signal_name -> Path (예: hr, ibi, eda, ppg)
    survey_dir: Path = None


class SessionLoader:
    """
    home_dir/bags/<trial_folder_name>/ 하나를 스캔해서 TrialData로 정리.
    """

    def __init__(self, home_dir: str):
        self.home_dir = Path(home_dir)
        self.bags_dir = self.home_dir / "bags"

    def list_trials(self) -> list[str]:
        if not self.bags_dir.exists():
            return []
        return sorted(p.name for p in self.bags_dir.iterdir() if p.is_dir())

    def load_trial(self, trial_folder_name: str) -> TrialData:
        trial_dir = self.bags_dir / trial_folder_name
        data = TrialData(trial_dir=trial_dir)

        data.cameras = self._scan_cameras(trial_dir / "camera")
        data.audio = self._scan_audio(trial_dir / "audio")
        data.imu = self._scan_imu(trial_dir / "imu")
        data.radar = self._scan_radar(trial_dir / "radar")
        data.watch = self._scan_watch(trial_dir / "watch")
        data.survey_dir = trial_dir / "survey"

        return data

    # ------------------------------------------------------------------
    def _scan_cameras(self, camera_dir: Path) -> dict:
        cameras: dict[tuple, CameraStreamFiles] = {}
        if not camera_dir.exists():
            return cameras

        # camera/{rgb,infrared,depth}/*.mp4, camera/{rgb,infrared,depth}/*_timestamps.csv
        for modality_subdir in camera_dir.iterdir():
            if not modality_subdir.is_dir():
                continue
            for mp4_path in sorted(modality_subdir.glob("*.mp4")):
                m = _CAMERA_FILE_RE.match(mp4_path.name)
                if not m:
                    continue
                raw_position = m.group("position")
                raw_modality = m.group("modality")
                seg_num = int(m.group("seg"))
                position = CAMERA_POSITION_ALIASES.get(raw_position, raw_position)
                modality = CAMERA_MODALITY_ALIASES.get(raw_modality, raw_modality)

                key = (position, modality)
                if key not in cameras:
                    cameras[key] = CameraStreamFiles(position=position, modality=modality)
                cameras[key].segment_files.append((seg_num, mp4_path))

            for csv_path in modality_subdir.glob("*_timestamps.csv"):
                m2 = re.match(r"^(?P<position>\w+?)_(?P<modality>color|infrared|depth)_timestamps\.csv$",
                               csv_path.name)
                if not m2:
                    continue
                position = CAMERA_POSITION_ALIASES.get(m2.group("position"), m2.group("position"))
                modality = CAMERA_MODALITY_ALIASES.get(m2.group("modality"), m2.group("modality"))
                key = (position, modality)
                if key not in cameras:
                    cameras[key] = CameraStreamFiles(position=position, modality=modality)
                cameras[key].timestamp_csv = csv_path

        for stream in cameras.values():
            stream.segment_files.sort(key=lambda t: t[0])

        return cameras

    def _scan_audio(self, audio_dir: Path) -> dict:
        audio = {}
        if not audio_dir.exists():
            return audio
        for wav_path in audio_dir.glob("*.wav"):
            mic_name = wav_path.stem  # 예: "dashboard_mic"
            ts_path = audio_dir / f"{mic_name}_timestamp.csv"
            if not ts_path.exists():
                ts_path = audio_dir / f"{mic_name}_timestamps.csv"
            audio[mic_name] = {
                "wav": wav_path,
                "timestamp_csv": ts_path if ts_path.exists() else None,
            }
        return audio

    def _scan_imu(self, imu_dir: Path) -> dict:
        imu = {}
        if not imu_dir.exists():
            return imu
        for csv_path in imu_dir.glob("*.csv"):
            if "accel" in csv_path.stem:
                imu["accel"] = csv_path
            elif "gyro" in csv_path.stem:
                imu["gyro"] = csv_path
        return imu

    def _scan_radar(self, radar_dir: Path) -> dict:
        """
        실제 구조: radar/radar_raw/segNNN/ 안에 bin+csv+cfg+sha+summary json.
        RadarTimestampIndex가 segNNN 폴더들을 직접 스캔하므로, 여기서는
        raw_dir 경로만 넘겨주면 됨 (개별 파일 목록은 만들지 않음).
        """
        radar = {}
        if not radar_dir.exists():
            return radar
        radar["raw_dir"] = radar_dir / "radar_raw"
        return radar

    def _scan_watch(self, watch_dir: Path) -> dict:
        watch = {}
        if not watch_dir.exists():
            return watch
        for csv_path in watch_dir.glob("*.csv"):
            watch[csv_path.stem] = csv_path  # 예: "watch_hr" -> path
        return watch
