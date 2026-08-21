# `front/widgets/timeline_widget.py`

전체 트라이얼 구간을 가로 바 하나로 그리는 커스텀 위젯. task window 마커,
확정 전 draft 구간, 재생헤드(playhead), 확대/이동된 보기 범위를 전부 이 위젯
하나가 그린다. `front/labeling_page.py`가 시나리오 페이지당 인스턴스 하나를
만든다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page.py` | `TimelineWidget, TimelineMarker` | `self.timeline` 하나를 만들어 task window/draft 마커를 채우고, 클릭/뷰 범위 시그널을 재생·스크롤바와 연결 |

## 두 종류의 "범위" - total과 view

`total_start`/`total_end`(트라이얼 전체 범위)와 `view_start`/`view_end`(현재
화면에 보이는 확대 범위)를 분리해서 관리한다. 전체 세션(수십 분)이 고정폭
바 하나에 그대로 매핑되면 몇 초짜리 액션을 픽셀 단위로 정밀하게 다루기
어려워서, 화면 좌표 변환(`_ts_to_x`/`_x_to_ts`)은 항상 `view_start`~`view_end`
기준으로 계산한다. 휠로 확대/축소, 우클릭 드래그로 이동한다.

## 시그널

- `position_clicked(float)`: 클릭(또는 좌클릭 드래그)한 지점의 절대시각.
  `LabelingPage`가 이 시그널을 받아 `playback.seek_to()`를 호출.
- `view_range_changed(float, float)`: 확대/이동으로 보이는 범위가 바뀔 때마다
  emit. `LabelingPage`가 스크롤바와 양방향 동기화하는 데 사용.

## 범위 조작 메서드

- `set_range(start_ts, end_ts)`: total 범위를 설정하고 view도 같이 total 전체로
  리셋.
- `set_view_range(start_ts, end_ts)`: 확대/이동된 view 범위를 지정. `total` 범위
  밖으로 못 벗어나게 clamp하고, 최소 폭(`MIN_VIEW_SPAN_SEC = 2.0`초)보다 안
  좁아지게도 clamp한다.
- `pan_by(fraction)`: 현재 보이는 구간(span)의 `fraction` 비율만큼 좌우 이동
  (음수면 왼쪽). "◀ 이동"/"이동 ▶" 버튼이 호출.
- `zoom_to_fit(start_ts, end_ts, padding_ratio=0.2)`: 특정 구간이 여백을 두고
  화면에 꽉 차게 확대. task window 전환, draft 클릭 시 호출됨.
- `reset_view()`: view를 total 전체로 리셋.

## `set_playhead(ts)` - 자동 따라가기

재생헤드가 확대된 view 가장자리 근처(`PLAYHEAD_FOLLOW_MARGIN_RATIO = 5%`
안쪽)까지 오면, 확대 폭은 그대로 유지한 채 view 범위 자체를 밀어서 재생헤드가
항상 보이게 따라간다. 확대해서 좁게 보고 있는 상태에서도 재생이 view 밖으로
나가버리지 않게 하기 위함.

## `paintEvent`

그려지는 순서(아래에서 위로):
1. 배경 트랙(회색 라운드 사각형).
2. task window 마커: 위쪽 브래킷(세로선 2개 + 가로선) + 라벨 텍스트. 라벨끼리
   시간상 가까우면(예: `pre_nback1`/`pre_nback2`가 몇십 초 간격) 겹칠 수 있어서,
   `QFontMetrics`로 각 라벨의 실제 폭을 재서 2단으로 번갈아 배치한다 -
   `row_end_x[row]`가 그 줄에서 마지막으로 그린 라벨이 끝난 x좌표를 기억해두고,
   새 라벨의 시작 x가 그보다 뒤면 같은 줄, 아니면 다른 줄에 배정.
3. 확정 전 draft 구간: 반투명 색 사각형(`color.setAlpha(120)`).
4. 현재 작업 중인 pending 선택 구간(시작/끝점 지정 중): 빨간 반투명 사각형.
   끝점이 아직 안 찍혔으면 재생헤드 위치를 임시 끝으로 사용.
5. 재생헤드: 빨간 세로선, 위젯 전체 높이.
6. **확대 중일 때만**(view가 total 전체가 아닐 때): 맨 위에 얇은 미니
   오버뷰 바 - 전체 범위 대비 지금 확대해서 보고 있는 구간이 어디인지
   표시.

`_ts_to_x`는 결과를 `[-1_000_000, 1_000_000]`으로 clamp한다 - 마커 시각이 보이는
범위를 크게 벗어나면(센서 간 시계가 크게 어긋난 경우 등) 비율 계산이 극단적으로
커져서 int 캐스팅 시 오버플로우/크래시가 날 수 있는 것을 막기 위한 방어적
처리.

## 마우스 입력

- 휠(`wheelEvent`): 커서가 가리키는 시각을 중심으로 확대/축소(`factor = 0.85`
  또는 `1/0.85`).
- 좌클릭(`mousePressEvent`/`mouseMoveEvent`): 클릭한(또는 드래그 중인) 위치의
  시각을 `position_clicked`로 emit - 클릭한 순간 그 위치로 재생 위치가 즉시
  이동한다.
- 우클릭 드래그(`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`): 화면
  이동(pan). `_pan_last_x`로 직전 드래그 x좌표를 기억해서 그 차이만큼
  `view_start`/`view_end`를 이동시킨다.

## `TimelineMarker` (dataclass)

`label`, `start_ts`, `end_ts`, `color`(기본 `"#4a90d9"`). task window 마커와
draft 마커 둘 다 이 타입으로 표현된다 - `LabelingPage`가 `TaskWindow`/
`LabelDraft`를 이 형태로 변환해서 넘긴다(`_load_task_window`의
`set_task_markers` 호출, `_refresh_draft_markers`의 `set_draft_markers` 호출).
