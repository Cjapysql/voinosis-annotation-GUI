# `front/playback_controller.py`

대시보드 마이크 오디오(`QMediaPlayer`)를 마스터 시계로 삼아, 그 재생 위치를
기준으로 절대시각을 계산해서 등록된 카메라 스트림들의 해당 프레임을 가져와
화면을 갱신하는 컨트롤러. `LabelingPage`가 시나리오 페이지 하나당 인스턴스
하나를 만든다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page.py` | `PlaybackController` | `self.playback` 하나를 만들어 재생/탐색/구간 미리보기 전부를 이 인스턴스에 위임 |

## 왜 오디오 신호를 직접 화면 갱신에 안 쓰는지

`QMediaPlayer.positionChanged`는 실측상 약 15Hz(64ms 간격)로만 갱신된다(백엔드
내부 폴링 주기, 조정 불가). 화면 갱신을 이 신호에 직접 묶으면 원본이 30fps여도
화면은 초당 15장 정도로만 바뀐다. 그래서 이 신호는 "마지막으로 확인된 오디오
위치 + 그 시각의 벽시계 시각"(`_audio_anchor_ms`/`_audio_anchor_wall`)만
기록하는 용도로 쓰고, 실제 화면 갱신은 별도의 33ms `QTimer`(`_display_timer`,
`_on_display_tick`)가 그 앵커 이후 흐른 실제 시간만큼 외삽(extrapolate)해서
계산한 절대시각으로 매 tick마다 갱신한다.

오디오가 없는 트라이얼(마이크 파일 누락 등)을 대비해, `_audio_player is None`이면
같은 디스플레이 타이머가 `_fallback_current_ts`를 직접 누적하는 폴백 모드로
동작한다.

## 상태

- `stream_players: dict[str, StreamPlayer]` / `frame_callbacks: dict[str, Callable]`:
  `register_stream(key, stream_player, on_frame)`으로 등록. `key`는
  `"driver_rgb"` 같은 문자열.
- `_audio_base_abs_ts`: 현재 오디오 wav 파일의 0ms 지점에 해당하는 절대
  unix time.
- `_audio_anchor_ms`/`_audio_anchor_wall`: 마지막으로 확인된 (오디오 위치
  ms, 그 시각의 `time.monotonic()`).
- `_playback_rate`: 재생 배속(기본 1.0).
- `_playback_limit_ts`: 설정돼 있으면 이 시각에서 자동 정지(구간 미리보기용,
  `set_playback_limit()`).

## 공개 메서드

- `set_audio(wav_path, base_abs_ts)`: 재생용 오디오 소스를 설정/교체. 이전
  플레이어가 있으면 먼저 정지 후 새 `QMediaPlayer`로 교체(마이크 전환
  대응), 기존 배속을 새 플레이어에도 적용, `positionChanged`/
  `mediaStatusChanged` 시그널 연결.
- `is_audio_ready` (프로퍼티): 오디오가 아예 없으면 `True`(기다릴 게 없음).
  있으면 `mediaStatus()`가 `LoadedMedia`/`BufferedMedia`인지 확인 - 실제로
  seek이 먹히는 상태인지.
- `set_playback_rate(rate)`: 배속 변경. 지금까지 경과한 시간을 옛 배속
  기준으로 먼저 앵커(`_audio_anchor_ms`)에 반영한 뒤 벽시계 기준점을 새로
  잡아서, 배속이 바뀌는 순간 위치가 튀지 않게 한다.
- `play()`/`pause()`/`stop()`: 재생 상태 전환. `play()`는 벽시계 기준점만
  새로 잡고 `_audio_anchor_ms` 값 자체는 건드리지 않는다(아래 "play()가
  position()을 다시 안 읽는 이유" 참고).
- `seek_to(abs_ts)`: 특정 절대시각으로 이동. 화면 갱신(`_update_all_frames`)은
  항상 요청받은 `abs_ts` 기준으로 동기적으로 수행하고, 오디오 위치 갱신
  (`setPosition`)은 best-effort로 별도 요청한다(아래 "seek_to가 화면을
  동기적으로 갱신하는 이유" 참고).
- `release()`: 등록된 모든 `StreamPlayer.release()` 호출 + 오디오 정지.

## `play()`가 `position()`을 다시 안 읽는 이유

`QMediaPlayer.setPosition()`은 비동기라, `seek_to()` 직후 바로 `play()`를
누르면 `position()`이 아직 이전 값(예: 0)을 돌려줄 수 있다. `play()`에서 그
값으로 다시 앵커를 잡으면 `seek_to()`가 지정한 위치가 아니라 엉뚱한 곳(주로
맨 처음)에서 재생이 시작되는 문제가 생긴다. `_audio_anchor_ms`는 `seek_to()`가
이미 정확히 기록해뒀으므로, `play()`는 그 값을 그대로 신뢰하고 벽시계
기준점(`_audio_anchor_wall`)만 새로 잡는다.

## `seek_to()`가 화면을 동기적으로 갱신하는 이유

오디오가 있을 때 화면 갱신을 `QMediaPlayer`의 `positionChanged` 신호에만
맡기면, 요청한 시각이 오디오 커버 범위 밖이라 ms가 0으로 clamp되고 마침 이미
위치가 0이면 Qt가 신호를 아예 안 쏴서 화면이 멈춘 것처럼 보이는 문제가 있었다.
그래서 `seek_to()`는 오디오 위치 갱신과 별개로, 항상 요청받은 `abs_ts`로
`_update_all_frames()`를 즉시 호출한다.

## `_on_audio_media_status_changed(status)`

`setPosition()`은 미디어가 아직 로딩 중일 때 호출하면 조용히 무시될 수 있다
(스티칭된 wav가 수백 MB라 로딩에 시간이 걸림) - 페이지 진입 직후 `seek_to()`로
특정 태스크 위치로 이동시켜도 그 시점에 로딩이 안 끝났으면 반영이 안 된 채
넘어갈 수 있다. 미디어 상태가 `LoadedMedia`/`BufferedMedia`로 바뀌는 시점에
`_audio_anchor_ms`(우리가 기록해둔 목표 위치)를 다시 적용해서 확실히
반영시키고, `audio_ready` 시그널을 emit한다(`front/main_window.py`가 이 시그널을
기다렸다가 화면을 전환).

## `_on_display_tick()` - 조기 정지 방지

매 33ms 틱마다:
1. 오디오가 있으면 `_audio_anchor_ms + (지금 벽시계 - 앵커 벽시계) * 1000 *
   배속`으로 현재 위치를 추정(`estimated_ms`).
2. `effective_end`(구간 미리보기 한계 또는 `total_end_ts`)에 도달했으면
   바로 정지하지 않고, 마지막으로 실제 확인된 오디오 위치
   (`_audio_anchor_ms` 기준 `real_abs_ts`)가 아직 한계 미만이면 화면만
   한계값으로 고정해두고 정지는 보류한다 - 추정치는 오디오가 버퍼링 등으로
   잠깐 멈칫해도 벽시계만 믿고 계속 흘러서, 아직 안 끝난 구간을 끝났다고
   착각해 조기 정지할 수 있기 때문. 다음 틱들에서 실제 위치가 한계에
   도달했을 때만 진짜로 `pause()`한다.
3. `_update_all_frames(abs_ts)`로 등록된 모든 스트림을 갱신하고
   `time_changed` emit.
