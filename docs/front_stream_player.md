# `front/stream_player.py`

카메라 스트림 하나(예: `driver_rgb`)에 대해 "절대시각 t에 해당하는 프레임을
가져와라"라는 요청을 실제 `cv2.VideoCapture` 호출로 옮기는 얇은 래퍼. `back/
timestamp_index.py`의 `CameraTimestampIndex`가 "이 시각은 어느 파일의 몇 번째
프레임인지"까지만 계산해주고, 실제로 그 파일을 열어서 프레임을 읽는 건 이
클래스가 한다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/playback_controller.py` | `StreamPlayer` | 타입 힌트, `register_stream()`으로 등록받은 인스턴스를 재생 매 틱마다 호출 |
| `front/labeling_page.py` | `StreamPlayer` | 카메라 스트림(최대 6개, `DISPLAY_STREAMS`)마다 인스턴스를 만들어 `PlaybackController`에 등록 |

## `StreamPlayer.__init__(index, flip_180=False)`

`index`는 `CameraTimestampIndex` 인스턴스(스트림 하나당 하나, `LabelingPage`가
페이지 로드 시 미리 만들어둔 것을 그대로 받음). `flip_180`이 `True`면
`road` 포지션 카메라처럼 광축 기준 180도 돌아간 채 장착된 스트림을 화면에
보여주기 전에 보정한다(export 시 적용되는 것과 같은 보정,
`back/segment_exporter.py`).

내부 상태: `_cap`(현재 열려있는 `cv2.VideoCapture`), `_cap_path`(그 cap이 어느
파일을 열고 있는지), `_local_pos`(마지막으로 읽은 로컬 프레임 인덱스),
`_last_frame`(마지막으로 읽은 프레임 - 캐시).

## `frame_at_time(t) -> np.ndarray | None`

1. `self.index.frame_at_time(t)`로 (파일 경로, 로컬 프레임 인덱스)를 구함.
   `None`이면(이 스트림에 유효한 시각 정보 자체가 없음) `None` 반환.
2. 요청한 파일이 지금 열려있는 파일과 다르면 기존 `cap`을 닫고 새로 연다
   (`_local_pos`를 -1로 리셋).
3. **요청한 로컬 인덱스가 방금 읽은 것과 같으면** 다시 디코딩하지 않고
   `_last_frame`을 그대로 반환(같은 시각을 반복 조회하는 경우 - 예: 재생이
   멈춰있을 때 화면 갱신 타이머가 계속 도는 경우).
4. **요청한 로컬 인덱스가 직전 + 1이면** `cap.read()`를 그대로 호출(순차
   재생 - 빠름, 정방향 재생 중 대부분의 경우).
5. **그 외의 경우**(뒤로 이동, 앞으로 건너뛰기, 스크러빙) `cap.set(POS_FRAMES,
   local_start)`으로 탐색한 뒤 `read()`.
6. 성공하면 `flip_180`이면 회전 적용 후 `_local_pos`/`_last_frame` 갱신.

이 순차/탐색 자동 판단은 `back/segment_exporter.py._write_video_cut`의 seek+검증
+폴백 로직과는 별개다 - 여기(재생)는 항상 `cap.set()`이 정확하다고 그대로
신뢰하고 쓰지만(재생은 화면에 살짝 어긋난 프레임이 보여도 치명적이지 않음),
export 쪽은 실제 도달 위치를 검증하고 어긋나면 순차 디코딩으로 폴백한다(잘라낸
결과물의 정확도가 중요하므로).

## `release()`

열려있는 `cap`을 닫는다. `LabelingPage`가 페이지를 정리할 때
(`PlaybackController.release()`를 통해) 등록된 모든 `StreamPlayer`에 대해 호출.
