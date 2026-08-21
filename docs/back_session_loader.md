# `back/session_loader.py`

원본 수집 데이터 폴더(`<home_dir>/bags/<trial_folder_name>/`)를 스캔해서, 센서별로
어떤 파일이 있는지 정리한 `TrialData`를 만든다. 파일 존재 여부와 이름 패턴만
다루고, 파일 안의 timestamp 값을 읽거나 해석하지는 않는다(그건 `timestamp_index.py`,
`radar_index.py`, `coverage.py`의 역할).

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `back/segment_exporter.py` | `TrialData, CameraStreamFiles, AudioStreamFiles` | export 시 각 스트림의 `segment_files`를 순회 |
| `back/audio_stitcher.py` | `AudioStreamFiles` | 재생용 연속 wav를 만들 때 세그먼트 목록을 읽음 |
| `front/labeling_page.py`, `front/labeling_page_loader.py` | `TrialData` | 타입 힌트, 페이지 생성 시 그대로 보관(`self.trial`) |
| `front/start_page.py`, `front/main_window.py` | `SessionLoader` | 트라이얼 목록 조회(`list_trials`), 선택된 트라이얼 로드(`load_trial`) |
| `check_av_frames.py` | `SessionLoader` | 진단 스크립트에서 트라이얼 로드 |

## 원본 폴더 구조

```
camera/{modality}/seg{NNN}/{position}_{modality}.mp4
camera/{modality}/seg{NNN}/{position}_{modality}_timestamps.csv
audio/seg{NNN}/{mic}.wav
audio/seg{NNN}/{mic}_timestamps.csv (또는 {mic}_timestamp.csv, 둘 다 시도)
IMU/seg{NNN}/camera_accel.csv, camera_gyro.csv
watch/seg{NNN}/watch_*.csv
radar/radar_raw/seg{NNN}/  (이 파일이 아니라 RadarTimestampIndex가 직접 스캔)
```

`seg{NNN}` 폴더 하나마다 그 세그먼트만의 media 파일과 자기 timestamp csv를 따로
갖는다 - 세그먼트 경계가 폴더 구조로 이미 명확하게 나뉘어 있다는 뜻이고, 이후
`timestamp_index.py`/`coverage.py`가 이 경계를 그대로 신뢰해서 쓴다(같은 csv를
여러 세그먼트가 공유하는 경우를 gap 감지로 나누는 처리 없이).

`position`/`modality` 원본 표기(`front`/`behavior`/`road`, `color`/`infrared`/`depth`)는
`CAMERA_POSITION_ALIASES`/`CAMERA_MODALITY_ALIASES`로 각각 `driver`/`behavior`/`road`,
`rgb`/`infrared`/`depth`로 정규화되어 저장된다 - 이후 코드 전체가 정규화된 이름만
다룬다.

seg 번호는 녹화 중단/재개마다 붙는 것으로 파악되며 연속이 아닐 수 있다(001, 003,
006 등) - 정렬 순서만 신뢰하고 번호 값 자체는 신뢰하지 않는다
(`stream.segment_files.sort(key=lambda t: t[0])`).

세그먼트 파일명에 mic/position/modality만 있고 seg 번호가 없기 때문에(`seg{NNN}/`
폴더명에만 seg 번호가 있음), 스캔 코드는 파일명이 아니라 상위 폴더명에서 seg
번호를 읽는다(`_SEG_DIR_RE`).

## 데이터 클래스

### `CameraStreamFiles`
- `position`/`modality`: 정규화된 이름.
- `segment_files: list[(seg_num, media_path, timestamp_csv_path|None)]`, seg_num
  오름차순 정렬됨. 세그먼트 폴더마다 자기 csv를 따로 가지므로 원소마다 다른 Path.

### `AudioStreamFiles`
- `mic_name`, `segment_files`: `CameraStreamFiles`와 같은 3-튜플 리스트 형태.

### `TrialData`
트라이얼 하나의 전체 스캔 결과를 담는 컨테이너.
- `cameras: dict[(position, modality), CameraStreamFiles]`
- `audio: dict[mic_name, AudioStreamFiles]`
- `imu: dict["accel"|"gyro", list[Path]]` - 세그먼트별 csv가 리스트로 쌓임(값이
  `Path` 하나가 아니라 리스트인 이유는 아래 `_scan_imu` 설명 참고).
- `radar: dict["raw_dir", Path]` - `RadarTimestampIndex`에 그대로 넘겨줄 디렉토리
  경로만 담음, 개별 파일 목록은 안 만듦.
- `watch: dict[signal_name, list[Path]]` - 예: `"watch_hr"` -> `[Path, ...]`.
- `survey_dir: Path`

## `SessionLoader`

- `list_trials() -> list[str]`: `home_dir/bags/` 아래 디렉토리 이름을 정렬해서
  반환. `front/start_page.py`가 홈 디렉토리 선택 후 트라이얼 드롭다운을 채울 때
  호출.
- `load_trial(trial_folder_name) -> TrialData`: 실제 스캔 진입점. 카메라/오디오/IMU/
  레이더/워치를 각각 `_scan_*` 메서드로 채우고, `survey_dir`은 스캔 없이 경로만
  기록(파싱은 `SurveyParser`가 별도로 함).
- `_resolve_dir(trial_dir, *name_candidates)`: 폴더 이름 대소문자 표기가 실측
  데이터마다 다를 수 있어서(`IMU` 폴더가 대문자로 온 사례 있었음) 후보 이름을
  순서대로 시도. 지금 실제로 이 방식을 쓰는 곳은 IMU 하나뿐
  (`_scan_imu(self._resolve_dir(trial_dir, "IMU", "imu"))`).

### `_scan_cameras`/`_scan_camera_files`

`_scan_cameras`가 `camera/{modality}/` 아래 `seg{NNN}/` 폴더들을 찾아서 각각
`_scan_camera_files`로 스캔한다.

`_scan_camera_files`는 한 세그먼트 폴더 안에 여러 스트림(예: `front_color`,
`behavior_color`, `road_color`)의 mp4+csv가 섞여 있다는 전제로 동작한다 - 먼저 그
폴더의 모든 `*_timestamps.csv`를 `(position, modality)` 키로 모아두고(`ts_paths`),
각 mp4를 처리할 때 자기 키에 해당하는 csv만 짝지어준다. "폴더 안 csv 하나 = 이
스트림 것"으로 가정하지 않는 이유는, `seg{NNN}/` 폴더 하나에 스트림별 파일이
여러 개 같이 들어있기 때문이다.

### `_scan_audio`/`_scan_audio_files`

같은 패턴으로 `audio/seg{NNN}/`을 스캔한다. timestamp csv 파일명이
`{mic}_timestamp.csv`(단수)와 `{mic}_timestamps.csv`(복수) 두 형태를 실측
데이터에서 다 시도한다(어느 쪽이 맞는지 확정되지 않아 방어적으로 둘 다 시도).

### `_scan_imu`/`_scan_watch`가 `dict[str, list[Path]]`인 이유

값이 `Path` 하나가 아니라 `list[Path]`인 이유는 세그먼트가 여러 개면 같은
센서 이름(`"accel"`, `"watch_hr"` 등)의 csv가 세그먼트 개수만큼 생기기 때문이다.
과거엔 `dict[str, Path]`(마지막으로 찾은 파일 하나만 저장)였는데, 이러면 스캔
순서상 나중에 발견된 세그먼트가 앞선 세그먼트를 덮어써서 앞쪽 세그먼트의 데이터가
조용히 사라지는 문제가 있었다 - 리스트로 바꿔서 모든 세그먼트를 보존하도록
수정됨. `back/segment_exporter.py`의 `_export_imu`/`_export_watch`가 이 리스트를
전부 순회하며 라벨 구간에 걸치는 행을 모아 합친다.

### `_scan_radar`

다른 스캔 메서드와 달리 개별 파일을 찾지 않는다 - `radar/radar_raw/` 디렉토리
경로 하나만 `TrialData.radar["raw_dir"]`에 기록해두고, 그 안의 `seg{NNN}/` 폴더별
bin/csv/cfg 파일을 실제로 찾아 읽는 일은 `back/radar_index.py`의
`RadarTimestampIndex`가 맡는다.
