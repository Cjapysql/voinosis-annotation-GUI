# `back/audio_stitcher.py`

세그먼트로 쪼개진 wav 파일 여러 개를, 세그먼트 사이의 무음(gap)까지 실제 무음
데이터로 채워서 하나의 연속된 wav로 합친다. 재생 전용 - 최종 저장(export)은
이 결과물을 쓰지 않고 원본 세그먼트 파일을 직접 다시 연다(`back/segment_exporter.py`).

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page_loader.py` | `build_continuous_audio` | 페이지 로드 시 백그라운드 스레드에서 기본 마이크의 연속 wav 생성 |
| `front/labeling_page.py` | `build_continuous_audio` | 라벨러가 재생 중 마이크를 바꿀 때(`_on_audio_stream_changed`) 다시 호출 |

## 왜 필요한지

`front/playback_controller.py`의 `PlaybackController`는 `QMediaPlayer` 파일 하나를
마스터 시계로 삼아서, "경과 시간(절대시각 - base_ts) == 파일 내 위치"라는 단순한
선형 공식으로 재생 위치를 계산한다(자세한 내용은 `docs/front_playback_controller.md`).
이 공식이 트라이얼 처음부터 끝까지 어긋나지 않으려면 재생용 오디오가 세그먼트
여러 개로 쪼개진 상태가 아니라 하나의 연속된 파일이어야 한다 - 그래서 재생 직전에
미리 이어붙인다.

## `build_continuous_audio(audio, cache_dir, reference_segment_starts=None)`

반환값: `(이어붙인 wav 경로, 그 wav 0초 지점의 절대 unix time)` 또는 세그먼트가
아예 없으면 `None`.

### 처리 순서

1. `AudioTimestampIndex(audio.segment_files, reference_segment_starts=...)`로 세그먼트별
   절대 시작 시각(`segment_starts`)을 구한다. 이 값을 못 구하면(빈 리스트) `None` 반환.
2. **캐시 확인**: 출력 파일(`{mic_name}_stitched.wav`)이 이미 있고, 그 mtime이 모든
   원본 세그먼트 파일의 mtime보다 최신이면 다시 만들지 않고 그대로 반환한다. 원본
   세그먼트 파일 자체는 안 바뀌므로, 한 번 만든 뒤로는 대부분 이 캐시가 히트한다.
3. 세그먼트를 순서대로 순회하며 이어붙인다(아래 "세그먼트 경계 처리" 참고).

### 세그먼트 경계 처리

두 가지를 각 세그먼트마다 처리한다:

- **세그먼트 사이 공백을 무음으로 채움**: `video_seg_start - cursor_ts`가 양수면
  (이번 세그먼트가 시작해야 할 절대 시각이 지금까지 이어붙인 커서보다 늦으면) 그
  차이만큼 0으로 채운 PCM 프레임을 먼저 써넣는다.
- **세그먼트 자체 길이를 다음 세그먼트 시작 시각까지로 자름**: 실측상 오디오
  세그먼트 파일의 실제 길이가 비디오가 선언한(다음 세그먼트가 시작해야 할) 시각보다
  항상 더 길다(세그먼트당 최대 1.5초 차이 관측됨). 그래서 각 세그먼트는
  `index.segment_starts[i+1] - cursor_ts`(다음 세그먼트가 시작할 때까지 남은 시간)
  만큼만 쓰고, 넘치는 꼬리는 버린다. 자기 길이가 그보다 짧으면 자연히 다음 반복의
  "공백을 무음으로 채움" 처리가 그 차이를 메운다. 마지막 세그먼트는 자를 다음
  경계가 없으므로 전체를 그대로 쓴다.

이렇게 해서 세그먼트 경계마다 커서가 항상 정확히 비디오가 선언한 시각과 일치하게
되고, 절대시각 -> 파일위치 매핑이 파일 끝까지 선형으로 유지된다.

### `reference_segment_starts` 인자

`AudioTimestampIndex` 생성자에 그대로 전달된다(`docs/back_timestamp_index.md`
참고) - 오디오 자체 timestamp csv가 청크 단위라 sparse해서 일부 세그먼트만 실측
데이터가 있으면 엉뚱한 세그먼트로 오인할 수 있다는 이유로 존재하는 보조 값.
`front/labeling_page_loader.py`가 카메라 스트림의 `segment_starts`를 이 인자로
넘긴다(`_reference_segment_starts` 헬퍼, `docs/front_labeling_page_loader.md` 참고).

## 호출 시점

- **페이지 로드 시**: `LabelingPageDataLoader.run()`(백그라운드 스레드)이 기본 마이크
  (`"ecms1_audio"` 우선)에 대해 1회 호출.
- **마이크 전환 시**: 라벨러가 화면의 마이크 선택 콤보박스를 바꾸면
  `_on_audio_stream_changed()`가 `_load_selected_audio()`를 호출하고, 그 안에서
  새로 고른 마이크에 대해 다시 호출한다(메인 스레드에서 동기 호출 - 이미 캐시된
  wav가 있으면 바로 반환되므로 빠름).
