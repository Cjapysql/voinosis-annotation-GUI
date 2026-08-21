# `front/labeling_page_loader.py`

`LabelingPage`를 실제로 만들기 전에 필요한 무거운 계산(카메라 세그먼트별
timestamp csv 파싱, 오디오 세그먼트 이어붙이기, 센서 커버리지 조회)을
백그라운드 스레드에서 먼저 끝내두는 로더.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `LabelingPageDataLoader` | "라벨링 시작" 버튼을 눌렀을 때 이 로더를 시작하고, `loaded` 시그널을 받으면 `LabelingPage`를 만듦 |

## 왜 필요한지

카메라 인덱스 생성(`back/timestamp_index.py`)과 오디오 스티칭(`back/
audio_stitcher.py`)은 Qt에 의존하지 않는 `back/` 계층 로직이라 스레드에서
안전하게 돌릴 수 있다. 반면 `LabelingPage`(`QWidget`)는 반드시 메인 스레드에서
만들어야 한다. 이 무거운 계산을 `LabelingPage` 생성자 안에서 직접 하면
(실측 5초 이상) 화면 전환이 멈춰 OS가 "응답 없음"을 띄운다 - 이 로더가 계산만
먼저 백그라운드에서 끝내고, 그 결과를 `LabelingPage` 생성자에 미리 계산된
값으로 넘겨서 생성자 자체는 빠르게 끝나게 한다.

## `_DISPLAY_STREAM_KEYS`/`_reference_segment_starts`

`front/labeling_page.py`의 `DISPLAY_STREAMS` 순서와 반드시 같은 우선순위
목록을 이 파일에 별도로(중복해서) 갖고 있다 - 오디오 세그먼트 경계 판단의
기준으로 쓸 카메라 스트림을 두 파일에서 항상 같은 순서로 고르기 위함(카메라마다
fps 실측 오차가 미세하게 달라서, 매번 다른 스트림을 기준으로 삼으면 세그먼트
판단이 흔들릴 수 있음). `back/segment_exporter.py`의
`_CAMERA_REFERENCE_PRIORITY`도 같은 목록을 별도로 갖고 있다 - 세 곳이 각자
같은 리스트를 유지해야 하므로, 한쪽을 바꾸면 나머지도 같이 바꿔야 한다.

`_reference_segment_starts(camera_indices, expected_count)`: 우선순위 순서로
카메라 스트림을 확인해서, 세그먼트 개수가 `expected_count`와 일치하는 첫
스트림의 `segment_starts`를 반환.

## `LabelingPageDataLoader(QThread)`

### `loaded`/`failed` 시그널

`loaded = Signal(object, object, object, object)` - `(camera_indices,
default_mic_name|None, audio_result|None, sensor_coverage)`. 타입을 `dict`가
아니라 `object`로 선언한 이유: `camera_indices`가 튜플 키를 가진 dict인데,
`Signal(dict, ...)`로 선언하면 PySide6가 스레드 간 큐잉 시 C++ 타입으로
변환하려다 실패한다(dict 값이 `CameraTimestampIndex` 커스텀 객체라서 더더욱
안 됨) - `object`로 선언하면 파이썬 객체를 그대로 통과시킨다.

### `run()`

1. 트라이얼의 모든 카메라 스트림에 대해 `CameraTimestampIndex`를 만들어
   `camera_indices` dict에 채움.
2. 오디오 마이크가 있으면 기본 마이크(`"ecms1_audio"` 우선, 없으면 첫 번째)를
   고르고, `_reference_segment_starts`로 참조 시작 시각을 구해
   `build_continuous_audio`를 호출.
3. `compute_sensor_coverage(self.trial)`(`back/coverage.py`)로 오디오/IMU/워치/
   레이더의 대략적인 커버리지를 계산 - 카메라는 1번에서 이미 정확하게 계산했으므로
   여기 포함 안 함.
4. 예외가 나면 `failed` emit, 아니면 `loaded` emit.

`front/main_window.py`가 `loaded`를 받으면 `_finish_open_labeling()`을 호출해서
이 네 값을 그대로 `LabelingPage` 생성자에 전달한다.
