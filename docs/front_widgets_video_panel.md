# `front/widgets/video_panel.py`

카메라 프레임(`np.ndarray`, BGR) 하나를 표시하는 `QLabel` 기반 패널. 화면
분할(최대 6개 패널)의 각 칸이 이 클래스의 인스턴스.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page.py` | `VideoPanel` | `DISPLAY_STREAMS` 순서대로 패널을 만들어 그리드에 배치, `PlaybackController.register_stream()`의 `on_frame` 콜백으로 `update_frame`을 등록 |

## 두 가지 "빈 화면" 상태

라벨러가 "화면이 왜 비었는지" 헷갈리지 않도록 구분한다:
- `set_unavailable(reason=...)`: **이 트라이얼에 해당 스트림 자체가 없음**
  (파일이 아예 없어서 재생 등록조차 안 됨) - 세션 내내 고정된 상태.
- `update_frame(None)`: **스트림은 있는데 지금 이 시각엔 프레임이 없음**
  (세그먼트 사이 gap, 녹화 범위 밖 등) - 재생 중 시시각각 바뀔 수 있음.

두 경우 다 화면엔 텍스트로 이유가 표시되지만, 문구가 다르다
(`"이 트라이얼에 해당 스트림 없음"` vs `"데이터 없음: 이 시각엔 녹화된
프레임이 없음"`).

## `clicked` 시그널

`mousePressEvent`에서 `super().mousePressEvent(event)` 호출 뒤(포커스 처리를
먼저 하도록) `clicked.emit()`. `LabelingPage`가 이 시그널을 받아 재생 중
"구간 미리보기 한계"(`playback.set_playback_limit`)를 해제한다 - 영상 화면을
클릭하는 것도 "이제 자유롭게 탐색하겠다"는 신호로 취급.

`setFocusPolicy(Qt.ClickFocus)`도 같이 설정돼 있다 - `QLabel` 자체엔
`keyPressEvent`가 없어서, 패널을 클릭해 포커스를 얻어도 스페이스/방향키
입력은 그대로 부모(`LabelingPage`)로 전달된다. 이 설정이 없으면 패널
클릭 후 재생/탐색 단축키가 안 먹힐 수 있다.

## `update_frame(frame)`

`frame`이 `None`이면 위의 "데이터 없음" 텍스트로 전환. 아니면:
1. `frame.ndim == 2`(흑백/depth 등 단일 채널)면 `cv2.normalize`로 0~255
   범위로 정규화한 뒤 `COLOR_GRAY2RGB`로 3채널 변환.
2. 아니면 `COLOR_BGR2RGB`(OpenCV 기본 BGR -> Qt가 기대하는 RGB).
3. `QImage` -> `QPixmap`으로 변환, `scaled(..., KeepAspectRatio,
   SmoothTransformation)`로 패널 크기에 맞춰 비율 유지 리사이즈.

`_unavailable` 상태인 패널은 이 메서드가 호출돼도 아무 것도 안 하고
반환한다(원래 애초에 스트림이 없는 패널은 `PlaybackController`에 등록되지
않으므로 보통 호출될 일이 없음 - 방어적 처리).
