# `back/timestamp_index.py`

절대시각(t_sec)과 센서 파일 안의 로컬 프레임/샘플 위치를 서로 변환하는 모듈.
`CameraTimestampIndex`(영상)와 `AudioTimestampIndex`(오디오) 두 클래스, 그리고 둘이
공유하는 모듈 레벨 헬퍼 함수들로 구성된다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `back/segment_exporter.py` | `CameraTimestampIndex, AudioTimestampIndex` | export 시 라벨 구간을 실제 파일 범위로 변환 |
| `back/audio_stitcher.py` | `AudioTimestampIndex` | 재생용 연속 wav를 만들 때 세그먼트 경계 파악 |
| `front/stream_player.py` | `CameraTimestampIndex` | 재생 중 절대시각 -> 프레임 조회(`frame_at_time`) |
| `front/labeling_page.py`, `front/labeling_page_loader.py` | `CameraTimestampIndex` | 페이지 로드 시 스트림별 인덱스 생성/보관 |
| `check_av_frames.py` | `CameraTimestampIndex` | 진단 스크립트에서 프레임 수/csv 정합성 확인 |

## 세그먼트별 timestamp csv

`back/session_loader.py`가 넘겨주는 `segment_files`는
`[(seg_num, media_path, timestamp_csv_path|None), ...]` 형태다. 세그먼트 폴더
하나마다 자기 csv를 따로 가지므로, 이 파일의 처리 로직은 "그 csv를 그 세그먼트
하나만의 정확한 데이터로 신뢰"하는 것을 기본으로 한다. 여러 세그먼트가 같은 csv
Path를 공유하는 경우(같은 csv 안에 여러 세그먼트의 데이터가 섞여 있는 경우)에도
대응하도록 `_load_segment_t_secs()`가 "같은 csv Path를 공유하는 세그먼트가 몇
개인지"를 보고 자동으로 gap 감지 분할(`_split_by_gap`)을 적용한다.

## 컬럼 스키마

- 카메라: `저장영상프레임번호`(정렬 순번), `동기화기준시각_sec`(정렬 기준 시각)
- 오디오: `저장오디오청크번호`(정렬 순번), `동기화기준시각_sec`(정렬 기준 시각)

정렬 기준 시각으로 `저장완료시각_sec`(디스크 저장 완료 시각, 저장 지연만큼 밀림)이
아니라 `동기화기준시각_sec`(센서가 실제 캡처한 시각)을 쓴다 - 다른 센서의 t_sec과
같은 축(실제 캡처 시각)이어야 정렬이 맞기 때문. `복제프레임여부`(드라이버 지연/드롭
시 직전 프레임을 복사해 mp4 프레임 수를 채운 표시) 컬럼은 무시하고 그대로 둔다 -
복제된 행은 직전 행과 동일한 시각이 한 번 더 찍히는 것뿐이라 gap 기반 세그먼트
경계 판단이나 시간→인덱스 선형 계산에 영향이 없다.

## fps를 실측 기반으로 보정하는 이유

`cv2.VideoCapture.get(CAP_PROP_FPS)`는 컨테이너에 박힌 명목값(예: 정확히 30.0)을
돌려주는데, 실측 timestamp가 있는 세그먼트에서 (첫 로그~마지막 로그 사이 실제
경과 시간)과 (그 사이 진짜 프레임 수)로 역산한 평균 fps는 7개 스트림 전부
일관되게 29.3~29.4 정도로 측정됐다. 이 차이를 무시하면 세그먼트 안에서 시간이
지날수록(끝쪽일수록) 최대 4~5초까지 어긋난다. `CameraTimestampIndex._calibrate_fps()`가
이 보정을 담당하고, 이후 프레임 위치 계산은 전부 이 보정된 값을 쓴다(cv2가
보고하는 명목 fps는 실측이 아예 없는 세그먼트의 최후 폴백으로만 쓰임).

## 세그먼트 시작 시각을 못 구한 세그먼트 채우기 (`_fill_segment_starts`)

세그먼트마다 자기 timestamp csv에서 첫 시각(`anchors[i]`)을 구할 수 있지만, csv가
없거나 비어있는 세그먼트는 `None`이 된다. `_fill_segment_starts(anchors, durations)`는
이런 자리를, 이웃 세그먼트의 시작 시각 + 자기 파일 길이(`durations`)로 앞/뒤 방향
모두 이어붙여서 역산한다(뒤에서 앞으로: 다음 세그먼트 시작 - 자기 길이, 앞에서
뒤로: 이전 세그먼트 시작 + 이전 길이). 이웃도 실측이 없어서 못 채우는 자리는
`None`으로 남고, `CameraTimestampIndex._compute_segment_starts()`/
`AudioTimestampIndex.__init__`가 최종적으로 하나라도 `None`이 남으면 그 스트림
전체를 빈 `segment_starts = []`로 처리한다(부분적으로만 신뢰할 수 있는 값을
쓰지 않고, 아예 이 스트림엔 유효한 시각 정보가 없다고 취급).

## `CameraTimestampIndex`

### 생성자에서 하는 일 (순서대로)

1. `_load_segment_t_secs(segment_files, "저장영상프레임번호", GAP_THRESHOLD_SEC)` -
   세그먼트별 t_sec 리스트.
2. `_probe_segment_info()` - 각 세그먼트 파일을 `cv2.VideoCapture`로 열어서
   (프레임 수, cv2가 보고하는 명목 fps)를 직접 읽음. csv와 무관하게 파일 자체에서
   읽는 값.
3. `_calibrate_fps()` - 위 두 결과로 실측 기반 fps 리스트 계산.
4. `_compute_segment_starts()` - 세그먼트별 절대 시작 시각(`self.segment_starts`,
   공개 속성). 다른 센서(오디오 등)가 이 값을 참조(reference)로 그대로 받아쓸 수
   있게 열어둔 속성.

### 메서드

- `first_t_sec`/`last_t_sec` (프로퍼티): 이 스트림 전체에서 가장 이른/늦은 절대
  시각. `front/labeling_page.py`의 `_compute_total_range()`와
  `_missing_sensor_coverage()`가 사용.
- `_segment_bounds(i)`: 세그먼트 i의 (절대 시작, 절대 끝) 시각.
- `frame_at_time(t)`: 절대시각 t에 가장 가까운 (파일 경로, 로컬 프레임 인덱스)를
  반환. t가 모든 세그먼트 범위 밖이면 가장 가까운 세그먼트의 처음/끝 프레임으로
  클램프한다(범위 밖이라고 `None`을 반환하지 않음) - `front/stream_player.py`의
  재생 중 프레임 조회가 이 메서드를 호출한다.
- `time_range_to_file_ranges(t_start, t_end)`: 절대시간 구간을
  `[(파일경로, local_start, local_end, 절대시작, 절대끝, fps), ...]`로 변환.
  `frame_at_time`과 달리 범위 밖이면 그 세그먼트를 결과에서 그냥 제외한다
  (클램프하지 않음). 뒤의 절대시작/절대끝/fps는 로컬 인덱스만으로는 "이 조각과
  다음 조각 사이에 공백이 얼마나 있는지"를 알 수 없어서 추가된 것 - export 시
  `back/segment_exporter.py._write_video_cut`가 이 결과를 순회하며 실제 프레임을
  잘라내고, 조각 사이/앞/뒤에 공백이 있으면 그 절대시각 차이만큼 경계 프레임을
  반복해서 채운다(재생 중 `frame_at_time`이 공백을 가장 가까운 프레임으로
  클램프하는 것과 같은 원칙 - `technical_reference.md` 2부 17번).

## `AudioTimestampIndex`

카메라와 컬럼 스키마는 비슷하지만(`저장오디오청크번호`), csv 한 행이 raw 샘플
1개가 아니라 청크(가변 길이) 이벤트라서 카메라처럼 "행 순서 = 프레임 순서"로
1:1 대응시킬 수 없다. 세그먼트 시작 절대시각만 구한 뒤, 그 안에서는 샘플 레이트가
일정하다는 가정으로 절대시각→로컬 샘플 인덱스를 선형 계산한다.

### 생성자: `reference_segment_starts` 파라미터

오디오는 카메라와 동일하게 먼저 자기 세그먼트별 timestamp csv로 스스로
`segment_starts`를 계산한다. `reference_segment_starts`는 그렇게 계산해도 여전히
못 채운 세그먼트가 있을 때만(자기 csv가 없거나 비어있고, 이웃으로도 역산이 안
되는 경우) 그 세그먼트에 한해서만 보조로 채워넣는 용도다 - 전체를 통째로
대체하지 않는다.

이 파라미터는 `list[float]` 또는 `() -> list[float]|None` 콜러블 둘 다 받을 수
있다. 콜러블로 넘기면 자기 데이터로 이미 다 채워진 경우(대부분) 그 콜러블 자체가
평가되지 않는다 - `back/segment_exporter.py`가 이 콜러블에 실제로 카메라 스트림의
`CameraTimestampIndex`를 새로 만드는 무거운 계산을 담아 넘기는데, 필요할 때만
계산하게 해서 최종 저장이 매번 몇 초~수십 초씩 걸리는 것을 피한다(자세한 배경은
`technical_reference.md` 2부 12번).

### 메서드

- `time_range_to_file_ranges(t_start, t_end)`: `CameraTimestampIndex`와 같은
  역할이지만 반환 단위가 로컬 샘플 인덱스, 튜플도 같은 형태로
  `(경로, local_start, local_end, 절대시작, 절대끝, 샘플레이트)`. `_export_audio`가
  이 결과로 `soundfile.SoundFile.seek()` + `read()`를 호출해서 실제 오디오
  데이터를 읽고, 조각 사이/앞/뒤 공백은 절대시작/끝 차이만큼 무음(0 PCM)으로
  채운다.
