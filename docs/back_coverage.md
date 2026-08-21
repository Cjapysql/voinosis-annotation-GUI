# `back/coverage.py`

센서별 대략적인 커버리지(세그먼트마다 첫 시각 ~ 마지막 시각)를 가볍게 조회하는
모듈. `CameraTimestampIndex`/`AudioTimestampIndex`/`RadarTimestampIndex`처럼
프레임/샘플 단위로 정확하게 인덱싱하지 않고, 각 csv의 첫 행과 마지막 행 시각만
읽는다. 이 세션 후반부에 추가된 모듈.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page_loader.py` | `compute_sensor_coverage` | 페이지 로드 시 백그라운드 스레드에서 1회 계산 |
| `front/labeling_page.py` | `range_overlaps_any` | task window를 고를 때마다 그 구간에 데이터 있는 센서/없는 센서 판정 |

## 왜 필요했는지

`front/labeling_page.py`의 "이 구간에 데이터가 없습니다" 경고 배너
(`coverage_warning_label`)가 원래 카메라만 체크하고 있어서, 오디오/IMU/워치/레이더가
빠진 구간을 라벨러가 화면상으로 알아챌 방법이 없었다. 카메라는 이미
`CameraTimestampIndex`로 프레임 단위 정확한 인덱스가 있지만, 이걸 오디오/IMU/워치/
레이더에도 똑같이(프레임 단위 정확도로) 적용하면 매번 무거운 파싱이 필요해서,
경고 배너처럼 정확도보다 속도가 중요한 곳에는 안 맞다. 그래서 첫/마지막 행만
읽는 훨씬 가벼운 전용 함수를 별도로 만들었다.

## 세그먼트를 하나로 뭉치면 안 되는 이유

센서 하나의 전체 커버리지를 "첫 세그먼트 시작 ~ 마지막 세그먼트 끝" 하나의
구간으로 뭉쳐서 표현하면, 세그먼트 사이에 실제로 녹화가 없던 공백까지
"커버됨"으로 오인하게 된다(실제로 겪은 사례: 오디오가 세그먼트 사이에 약 1시간
공백이 있었는데, 하나로 뭉친 범위로 보면 그 공백이 안 보임). 그래서
`compute_sensor_coverage()`는 센서 하나당 **세그먼트별 (시작, 끝) 쌍의 리스트**를
반환하고, 특정 구간에 데이터가 있는지는 `range_overlaps_any()`로 그 리스트의
세그먼트들과 개별적으로 겹치는지 확인한다.

## 함수

- `_csv_first_last_t_sec(csv_path, t_col_candidates)`: csv 헤더에서
  `_SENSOR_T_COLS = ("동기화기준시각_sec", "t_sec", "ros_time_sec", "timestamp")`
  중 실제로 있는 컬럼을 찾아, 첫 데이터 행과 마지막 데이터 행의 그 컬럼 값을
  반환. 카메라/오디오는 `동기화기준시각_sec`, IMU/워치는 `t_sec`, 레이더는
  `ros_time_sec`을 쓴다 - 센서마다 컬럼명이 다르므로 후보 목록에서 찾는 방식.
  실패(파일 없음/컬럼 없음/파싱 오류)하면 `None`.
- `_audio_stream_segments(stream)`: `AudioStreamFiles` 하나(마이크 하나)의
  `segment_files`를 순회하며 세그먼트별 (시작, 끝) 리스트를 만든다.
- `_csv_list_segments(csv_paths)`: IMU/워치처럼 이미 `list[Path]`로 돼 있는
  센서(`TrialData.imu`/`watch`의 값)에 대해 같은 방식으로 리스트를 만든다.
- `_radar_segments(raw_dir)`: `radar_raw/seg{NNN}/radar_frame_index_*.csv`를
  세그먼트 폴더 단위로 순회.
- `compute_sensor_coverage(trial)`: `TrialData` 하나를 받아
  `{표시용 이름: [(세그먼트1 시작,끝), (세그먼트2 시작,끝), ...]}` 딕셔너리를 만든다.
  이름은 `"오디오(ecms1_audio)"`, `"IMU(accel)"`, `"워치(watch_hr)"`, `"레이더"`
  형태 - 경고 배너 문구에 그대로 나열된다. **카메라는 포함하지 않는다** -
  호출부(`front/labeling_page.py`)가 이미 정확한 `CameraTimestampIndex`를
  갖고 있으므로 그걸 그대로 쓰면 된다.
- `range_overlaps_any(start_ts, end_ts, segments)`: `[start_ts, end_ts]`가
  `segments`(세그먼트별 (시작,끝) 리스트) 중 하나라도와 겹치면 `True`.

## 실제로 어떻게 쓰이는지

1. `front/labeling_page_loader.py`의 `LabelingPageDataLoader.run()`(백그라운드
   스레드)이 카메라 인덱스/오디오 스티칭과 함께 `compute_sensor_coverage(trial)`을
   1회 호출해서 `loaded` 시그널로 넘긴다(`camera_indices, default_mic_name,
   audio_result, sensor_coverage` 4개 값).
2. `front/main_window.py`가 이 값을 그대로 `LabelingPage` 생성자에 전달,
   `self.sensor_coverage`로 보관.
3. `LabelingPage._compute_total_range()`가 `self.sensor_coverage`에서 이름이
   `"오디오("`로 시작하는 항목만 골라 타임라인 전체 탐색 범위(`total_start`/
   `total_end`)에 합친다(카메라+오디오까지만 - 라벨러가 실제로 보고 듣는 대상
   기준. IMU/워치/레이더는 탐색 범위엔 안 넣음).
4. `LabelingPage._missing_sensor_coverage(start_ts, end_ts)`가 `task window`를
   고를 때마다(`_load_task_window`) `self.sensor_coverage`의 모든 항목을
   `range_overlaps_any`로 확인해서, 데이터 없는 센서 이름 목록을 만들고
   `coverage_warning_label`에 표시한다.

## 세그먼트 경계를 gap 감지 없이 그대로 신뢰하는 이유

이 모듈은 `back/timestamp_index.py`의 `_split_by_gap`/`GAP_THRESHOLD_SEC` 같은
gap 감지 로직을 쓰지 않는다 - 세그먼트 폴더 구조(`seg{NNN}/`)가 이미 정확한
세그먼트 경계이므로(`back/session_loader.py` 참고), 폴더로 나뉜 세그먼트 하나하나를
그대로 하나의 구간으로 신뢰하면 된다. 세그먼트 여러 개가 csv 하나를 공유하는
경우까지 이 모듈에서 다루지는 않는다.
