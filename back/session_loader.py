"""
원본 수집 데이터 폴더 (예: D:\\bags\\id12345_trial2_20260615_152028_승우) 탐색.

카메라/오디오/IMU/watch 폴더 구조가 두 가지 존재하며 (수집 파이프라인이 도중에
바뀐 것으로 추정), 이 스캐너는 둘 다 지원한다:

  구(舊) flat 구조 (예: id710_trial14_20260710_133516):
    camera/{modality}/{raw_position}_{raw_modality}_seg{NNN}.mp4
    camera/{modality}/{raw_position}_{raw_modality}_timestamps.csv  (스트림당 1개, 세그먼트 공유)
    audio/{mic}_seg{NNN}.wav
    IMU/camera_accel.csv, camera_gyro.csv
    watch/watch_*.csv
    예: front_depth_seg001.mp4, behavior_color_seg006.mp4, road_infrared_seg003.mp4

  신(新) 폴더 구조 (예: id9276_trial3_20260727_162156_total_test):
    camera/{modality}/seg{NNN}/{raw_position}_{raw_modality}.mp4  (파일명엔 seg 번호 없음)
    camera/{modality}/seg{NNN}/{raw_position}_{raw_modality}_timestamps.csv
    audio/seg{NNN}/{mic}.wav
    IMU/seg{NNN}/camera_accel.csv, camera_gyro.csv
    watch/seg{NNN}/watch_*.csv
    (radar는 원래부터 radar/radar_raw/seg{NNN}/ 구조라 이번 변경과 무관, RadarTimestampIndex가 처리)

  raw_position: front | behavior | road   -> 최종 저장 시 driver | behavior | road로 정규화
  raw_modality: color | infrared | depth  -> 최종 저장 시 rgb | infrared | depth로 정규화

  seg 번호는 녹화가 중단되었다가 재시작될 때마다 붙는 것으로 보이며,
  번호가 연속이 아닐 수 있음(001, 003, 006 등) -> 정렬만 하고 값 자체는 신뢰하지 않음.

  timestamp csv는 카메라/오디오 세그먼트 파일 하나하나에 개별로 붙여서
  (CameraStreamFiles.segment_files / AudioStreamFiles.segment_files의 3번째
  원소) 보관한다. flat 구조는 세그먼트 여러 개가 csv 하나를 공유하므로 같은
  Path가 반복되고(csv 안에서 세그먼트 경계를 gap 감지로 나눠야 함), 신 구조는
  세그먼트 폴더 하나마다 자기 csv가 따로 있고 그 csv는 그 세그먼트만의 정확한
  데이터라는 게 확인됨 - 두 경우 다 TimestampIndex 쪽에서 처리한다. csv 컬럼
  스키마(구: frame_idx/t_sec, 신: 저장영상프레임번호 등/동기화기준시각_sec)도
  TimestampIndex가 다룸, 이 파일은 파일 탐색/매칭만 담당.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

CAMERA_POSITION_ALIASES = {"front": "driver", "behavior": "behavior", "road": "road"}
CAMERA_MODALITY_ALIASES = {"color": "rgb", "infrared": "infrared", "depth": "depth"}

# flat 구조: seg 번호가 파일명에 포함
_CAMERA_FILE_RE = re.compile(
    r"^(?P<position>\w+?)_(?P<modality>color|infrared|depth)_seg(?P<seg>\d+)\.mp4$"
)
# 신 구조: seg 번호는 상위 seg{NNN} 폴더명에 있고 파일명엔 없음
_CAMERA_FILE_RE_NESTED = re.compile(
    r"^(?P<position>\w+?)_(?P<modality>color|infrared|depth)\.mp4$"
)
_CAMERA_TS_RE = re.compile(
    r"^(?P<position>\w+?)_(?P<modality>color|infrared|depth)_timestamps\.csv$"
)

_AUDIO_SEG_FILE_RE = re.compile(r"^(?P<mic>\w+?)_seg(?P<seg>\d+)\.wav$")

_SEG_DIR_RE = re.compile(r"^seg(?P<seg>\d+)$")


@dataclass
class CameraStreamFiles:
    position: str          # 정규화된 이름: driver | behavior | road
    modality: str          # 정규화된 이름: rgb | infrared | depth
    # [(seg_num, media_path, timestamp_csv_path|None), ...], seg 번호 오름차순 정렬됨.
    # flat 구조는 세그먼트 여러 개가 timestamp_csv_path를 공유(같은 Path가 반복됨) -
    # 세그먼트 경계는 나중에 gap 감지로 나눔. 신 구조는 세그먼트 폴더 하나당 자기
    # csv라 세그먼트마다 다른(자기 것만 담긴) Path.
    segment_files: list = field(default_factory=list)


@dataclass
class AudioStreamFiles:
    """카메라와 동일한 규칙: {mic}_seg{NNN}.wav 여러 개 + 공유 {mic}_timestamps.csv 1개
    (flat) 또는 세그먼트 폴더마다 자기 wav+csv(신 구조). (세그먼트가 안 나뉜 단일
    파일 {mic}.wav 형태도 seg_num=1짜리 리스트로 통일해서 다룸)"""
    mic_name: str
    segment_files: list = field(default_factory=list)  # [(seg_num, media_path, timestamp_csv_path|None), ...]


@dataclass
class TrialData:
    trial_dir: Path
    cameras: dict = field(default_factory=dict)   # (position, modality) -> CameraStreamFiles
    audio: dict = field(default_factory=dict)      # mic_name -> AudioStreamFiles
    imu: dict = field(default_factory=dict)        # "accel"/"gyro" -> [Path, ...] (세그먼트별, 구조는 1개)
    radar: dict = field(default_factory=dict)      # "raw_bin"/"timestamp_csv" -> Path
    watch: dict = field(default_factory=dict)      # signal_name -> [Path, ...] (예: hr, ibi, eda, ppg)
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
        data.imu = self._scan_imu(self._resolve_dir(trial_dir, "IMU", "imu"))
        data.radar = self._scan_radar(trial_dir / "radar")
        data.watch = self._scan_watch(trial_dir / "watch")
        data.survey_dir = trial_dir / "survey"

        return data

    @staticmethod
    def _resolve_dir(trial_dir: Path, *name_candidates: str) -> Path:
        """대소문자 표기가 실측 데이터마다 다를 수 있어서(IMU 폴더가 대문자로
        온 사례가 있었음) 후보 이름들을 순서대로 시도. 다 없으면 마지막 후보로 반환
        (어차피 _scan_* 쪽에서 exists() 체크 후 빈 dict를 반환하니 안전함)."""
        for name in name_candidates:
            candidate = trial_dir / name
            if candidate.exists():
                return candidate
        return trial_dir / name_candidates[-1]

    # ------------------------------------------------------------------
    def _scan_cameras(self, camera_dir: Path) -> dict:
        cameras: dict[tuple, CameraStreamFiles] = {}
        if not camera_dir.exists():
            return cameras

        # camera/{rgb,infrared,depth}/*.mp4 (flat 구조), 아니면
        # camera/{rgb,infrared,depth}/seg{NNN}/*.mp4 (신 구조) 둘 다 시도.
        for modality_subdir in camera_dir.iterdir():
            if not modality_subdir.is_dir():
                continue
            self._scan_camera_files(modality_subdir, seg_num=None, cameras=cameras)
            for seg_dir in sorted(modality_subdir.glob("seg*")):
                m_seg = _SEG_DIR_RE.match(seg_dir.name)
                if not m_seg or not seg_dir.is_dir():
                    continue
                self._scan_camera_files(seg_dir, seg_num=int(m_seg.group("seg")), cameras=cameras)

        for stream in cameras.values():
            stream.segment_files.sort(key=lambda t: t[0])

        return cameras

    @staticmethod
    def _scan_camera_files(scan_dir: Path, seg_num: int | None, cameras: dict) -> None:
        """scan_dir 하나(flat 구조면 modality 폴더 자체, 신 구조면 seg{NNN} 폴더)를 스캔.
        seg_num이 None이면 파일명에서 seg 번호를 읽고(flat), 아니면 인자로 받은
        seg_num을 그대로 쓴다(신 구조 - 파일명엔 seg 번호가 없음).

        같은 scan_dir 안에 여러 스트림(front_color, behavior_color, road_color 등)의
        mp4+csv가 섞여 있을 수 있으므로, 먼저 csv들을 (position, modality)별로
        모아두고 각 mp4는 자기 키에 해당하는 csv만 가져간다."""
        file_re = _CAMERA_FILE_RE if seg_num is None else _CAMERA_FILE_RE_NESTED

        ts_paths: dict[tuple, Path] = {}
        for csv_path in scan_dir.glob("*_timestamps.csv"):
            m2 = _CAMERA_TS_RE.match(csv_path.name)
            if not m2:
                continue
            position = CAMERA_POSITION_ALIASES.get(m2.group("position"), m2.group("position"))
            modality = CAMERA_MODALITY_ALIASES.get(m2.group("modality"), m2.group("modality"))
            ts_paths[(position, modality)] = csv_path

        for mp4_path in sorted(scan_dir.glob("*.mp4")):
            m = file_re.match(mp4_path.name)
            if not m:
                continue
            raw_position = m.group("position")
            raw_modality = m.group("modality")
            resolved_seg = seg_num if seg_num is not None else int(m.group("seg"))
            position = CAMERA_POSITION_ALIASES.get(raw_position, raw_position)
            modality = CAMERA_MODALITY_ALIASES.get(raw_modality, raw_modality)

            key = (position, modality)
            if key not in cameras:
                cameras[key] = CameraStreamFiles(position=position, modality=modality)
            cameras[key].segment_files.append((resolved_seg, mp4_path, ts_paths.get(key)))

    def _scan_audio(self, audio_dir: Path) -> dict:
        """{mic}_seg{NNN}.wav (+ 공유 {mic}_timestamps.csv, flat 구조) 또는
        seg{NNN}/{mic}.wav (+ seg{NNN}/{mic}_timestamps.csv, 신 구조) 둘 다 그룹핑.
        세그먼트 번호가 파일명에 없는 경우(신 구조, 혹은 애초에 세그먼트가 안 나뉜
        단일 파일)는 폴더에서 얻은 seg_num(없으면 1)으로 통일."""
        audio: dict[str, AudioStreamFiles] = {}
        if not audio_dir.exists():
            return audio

        self._scan_audio_files(audio_dir, seg_num=None, audio=audio)
        for seg_dir in sorted(audio_dir.glob("seg*")):
            m_seg = _SEG_DIR_RE.match(seg_dir.name)
            if not m_seg or not seg_dir.is_dir():
                continue
            self._scan_audio_files(seg_dir, seg_num=int(m_seg.group("seg")), audio=audio)

        for stream in audio.values():
            stream.segment_files.sort(key=lambda t: t[0])

        return audio

    @staticmethod
    def _scan_audio_files(scan_dir: Path, seg_num: int | None, audio: dict) -> None:
        for wav_path in sorted(scan_dir.glob("*.wav")):
            m = _AUDIO_SEG_FILE_RE.match(wav_path.name) if seg_num is None else None
            if m:
                mic_name = m.group("mic")
                resolved_seg = int(m.group("seg"))
            else:
                mic_name = wav_path.stem
                resolved_seg = seg_num if seg_num is not None else 1

            ts_path = scan_dir / f"{mic_name}_timestamp.csv"
            if not ts_path.exists():
                ts_path = scan_dir / f"{mic_name}_timestamps.csv"
            if not ts_path.exists():
                ts_path = None

            if mic_name not in audio:
                audio[mic_name] = AudioStreamFiles(mic_name=mic_name)
            audio[mic_name].segment_files.append((resolved_seg, wav_path, ts_path))

    def _scan_imu(self, imu_dir: Path) -> dict:
        """accel/gyro는 IMU/camera_accel.csv 하나뿐인 구조(flat)와, 세그먼트가
        나뉘면 IMU/seg{NNN}/camera_accel.csv가 세그먼트 개수만큼 있는 구조(신)
        둘 다 지원 - 그래서 값이 Path 하나가 아니라 [Path, ...] 리스트."""
        imu: dict[str, list] = {}
        if not imu_dir.exists():
            return imu
        csv_paths = list(imu_dir.glob("*.csv"))
        for seg_dir in sorted(imu_dir.glob("seg*")):
            if _SEG_DIR_RE.match(seg_dir.name) and seg_dir.is_dir():
                csv_paths.extend(sorted(seg_dir.glob("*.csv")))
        for csv_path in csv_paths:
            if "accel" in csv_path.stem:
                imu.setdefault("accel", []).append(csv_path)
            elif "gyro" in csv_path.stem:
                imu.setdefault("gyro", []).append(csv_path)
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
        """IMU와 동일한 이유로 값이 Path 하나가 아니라 [Path, ...] 리스트
        (세그먼트가 나뉘면 signal_name당 세그먼트 개수만큼 파일이 생김)."""
        watch: dict[str, list] = {}
        if not watch_dir.exists():
            return watch
        csv_paths = list(watch_dir.glob("*.csv"))
        for seg_dir in sorted(watch_dir.glob("seg*")):
            if _SEG_DIR_RE.match(seg_dir.name) and seg_dir.is_dir():
                csv_paths.extend(sorted(seg_dir.glob("*.csv")))
        for csv_path in csv_paths:
            watch.setdefault(csv_path.stem, []).append(csv_path)  # 예: "watch_hr" -> [path, ...]
        return watch
