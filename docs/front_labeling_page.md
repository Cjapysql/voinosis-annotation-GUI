# `front/labeling_page.py`

세 시나리오(distraction/drowsiness/cognitive) 공통 라벨링 화면. 타임라인 +
6분할 영상 + 라벨 폼 + draft 목록 + 최종 저장을 한 페이지 안에서 다룬다.
`back/`의 거의 모든 모듈과 `front/`의 나머지 컴포넌트(스트림 재생, 재생 컨트롤,
위젯 3종, export 워커)를 이 파일이 엮는다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `LabelingPage` | `LabelingPageDataLoader`가 끝난 뒤 `_finish_open_labeling()`에서 생성, 시나리오별로 캐시해서 재사용 |

## 이 파일이 가져다 쓰는 것

`back.models`(`Scenario, TaskWindow, DistractionTaskWindow, CognitiveTaskWindow,
LabelDraft`), `back.session_loader.TrialData`, `back.timestamp_index.
CameraTimestampIndex`, `back.draft_store.DraftStore`, `back.segment_exporter.
SegmentExporter`, `back.label_taxonomy.AreaTaxonomy`, `back.audio_stitcher.
build_continuous_audio`, `back.coverage.range_overlaps_any`,
`front.widgets.timeline_widget.{TimelineWidget, TimelineMarker}`,
`front.widgets.video_panel.VideoPanel`, `front.widgets.label_forms.
{DistractionLabelForm, DrowsinessLabelForm, CognitiveLabelForm}`,
`front.stream_player.StreamPlayer`, `front.playback_controller.
PlaybackController`, `front.export_worker.ExportWorker`.

## 모듈 상수

- `DISPLAY_STREAMS`: 화면에 표시할 카메라 조합, `(position, modality, 제목)`
  6개(`driver`/`behavior`/`road` × `rgb`/`infrared`). depth는 화면엔 안 띄우고
  백엔드(export)에서만 저장된다. `front/labeling_page_loader.py`의
  `_DISPLAY_STREAM_KEYS`, `back/segment_exporter.py`의
  `_CAMERA_REFERENCE_PRIORITY`와 순서를 맞춰 유지해야 하는 목록 중 하나
  (오디오 세그먼트 기준 스트림 선택에 영향).
- `MARKER_COLORS`: 시나리오별 타임라인 마커 색.

## 생성자 - 두 단계 구성의 두 번째 단계

`__init__`은 `camera_indices`, `default_mic_name`, `audio_result`,
`sensor_coverage` 네 값을 **필수로 받는다**(전부 `LabelingPageDataLoader`가
백그라운드 스레드에서 미리 계산해둔 것). 순서: `_compute_total_range()` ->
`_build_ui()` -> `_build_playback()` -> 첫 task window 로드 ->
`_refresh_progress_label()`.

## 키보드 처리

- `showEvent`: 페이지가 보일 때 포커스를 가져옴(`setFocus()`) - 방향키/스페이스가
  바로 먹히도록.
- `eventFilter`: `_build_ui()` 끝에서 모든 자식 위젯(`findChildren(QWidget)`)에
  설치됨. 스페이스바 입력을 가로채 항상 재생/일시정지 토글로 처리 - 버튼/
  콤보박스가 포커스를 가진 상태에서 스페이스바를 누르면 Qt 기본 동작(그
  위젯 재클릭/토글)이 먼저 실행되는 걸 막기 위함. 다른 키는 그대로 통과시킴.
- `keyPressEvent`: 스페이스(재생/일시정지), ←/→(1초 이동), Shift+←/→
  (`_step_frame`로 프레임 단위 이동).
- `_step_frame(direction)`: 재생 중이면 먼저 정지, 구간 미리보기 한계 해제,
  `frame_step_sec`(`_probe_frame_step()`이 실제 fps로 계산해둔 값) 단위로
  이동.

## 타임라인 전체 범위 계산 - `_compute_total_range()`

`docs/back_coverage.md`, 관련 논의 내용대로: **카메라 + 오디오 + task window**
시각만 전체 탐색 범위(`total_start`/`total_end`)에 포함시킨다. 라벨러가 실제로
보고 듣는 대상(영상+음성) 기준으로 탐색 가능 범위를 정한다는 원칙 - IMU/워치/
레이더는 라벨러가 직접 감상할 대상이 아니므로 여기 포함하지 않고, 대신
`_missing_sensor_coverage()`(경고 배너)에서만 다룬다.

## UI 구성 - `_build_ui()`

좌측(`stretch=3`): 뒤로가기 버튼, `TimelineWidget`, 확대/이동 버튼 행, 타임라인
스크롤바, 6분할 영상 그리드(`QGridLayout`, `DISPLAY_STREAMS` 순서로 3열 배치),
재생 컨트롤 행(재생/일시정지/정지/프레임 이동 버튼, 오디오 마이크 콤보박스,
배속 콤보박스).

우측(`stretch=2`, 사이드 패널): 시나리오 제목, `no_data_banner`(이 시나리오에
survey 데이터 자체가 없을 때), `progress_label`(진행 상황), `coverage_warning_label`
(센서 커버리지 경고), task window 콤보박스, 라벨 폼(`_make_label_form()`이
시나리오별로 다른 클래스 생성), 가이드라인 힌트(`boundaries_locked`인 시나리오만),
시작/끝점 지정 버튼, 가이드라인 리셋 버튼, 구간 저장 버튼, 작업 중인 구간
목록(`draft_list`), 수정/삭제 버튼, 최종 저장 버튼.

`window_combo`는 `currentIndexChanged`가 아니라 `activated`에 연결된다 -
`currentIndexChanged`는 선택값이 실제로 바뀔 때만 발생해서, 이미 선택된
항목을 다시 고르면 반응이 없는 문제가 있었다(`activated`는 사용자가 드롭다운
항목을 고르는 행위 자체에 반응해서 같은 항목을 다시 골라도 항상 발생).

`audio_combo`/`speed_combo`의 기본값(`setCurrentText`)은 `currentTextChanged`
시그널을 연결하기 **전에** 설정된다 - 연결 후 설정하면 그 시점엔 아직
`self.playback`이 만들어지지 않아서 핸들러가 호출될 때 에러가 난다.

## `_build_playback()`

`PlaybackController`를 만들고, `DISPLAY_STREAMS` 순서로 각 카메라 스트림에
대해 `StreamPlayer`(`road`면 `flip_180=True`)를 만들어 `register_stream()`으로
등록한다. 스트림이 없는(`camera_indices`에 키가 없는) 패널은
`panel.set_unavailable()`. 오디오는 `precomputed_audio_result`(로더가 이미
빌드해둔 것)를 그대로 `playback.set_audio()`에 넘긴다 - 마이크를 나중에
콤보박스에서 바꿀 때만 `_load_selected_audio()`가 다시 호출된다.

## 오디오 마이크/배속 전환

- `_select_audio_stream()`: `audio_combo`에서 고른 마이크 이름으로
  `AudioStreamFiles`를 조회.
- `_load_selected_audio()`: `_reference_segment_starts()`로 참조 시작 시각을
  구해 `build_continuous_audio()`를 다시 호출, 결과를
  `playback.set_audio()`에 반영.
- `_on_audio_stream_changed`: 재생 중이었으면 먼저 멈추고, 오디오를 다시
  로드한 뒤 현재 재생헤드 위치로 seek, 원래 재생 중이었으면 다시 재생.
- `_on_speed_changed`: 콤보박스 텍스트(`"1.5x"` 등)를 float로 파싱해
  `playback.set_playback_rate()`.
- `_reference_segment_starts(expected_count)`: `DISPLAY_STREAMS` 순서(고정
  우선순위)로 카메라 스트림을 확인해 세그먼트 개수가 일치하는 첫 스트림의
  `segment_starts`를 반환. `front/labeling_page_loader.py`의
  `_reference_segment_starts`, `back/segment_exporter.py`의
  `_reference_camera_segment_starts`와 같은 원칙(세 곳에 각자 구현돼 있음).

## 타임라인 ↔ 스크롤바 동기화

`_on_timeline_view_changed(view_start, view_end)`: `TimelineWidget`의
`view_range_changed` 시그널을 받아 스크롤바의 range/pageStep/value를 그
비율에 맞게 계산해서 반영(`_SCROLLBAR_RESOLUTION = 10000` 정수 해상도로
매핑). `_syncing_scrollbar` 플래그를 세워서 이 갱신이 다시 `_on_scrollbar_changed`를
트리거하지 않게 막는다.

`_on_scrollbar_changed(value)`: 라벨러가 스크롤바를 직접 조작했을 때만(플래그가
꺼져있을 때만) 타임라인의 `view_range`를 그 값에 맞게 이동시킨다.

## task window 로딩 - `_load_task_window(window)`

1. `current_window` 갱신, pending 선택 초기화, 구간 미리보기 한계 해제.
2. 전체 task window 마커를 타임라인에 다시 그림(`set_task_markers`),
   draft 마커도 갱신(`_refresh_draft_markers`).
3. 시나리오별로 라벨 폼에 프리필: drowsiness는 KSS 점수, cognitive는
   태스크명/난이도, distraction은 지시문 힌트.
4. `_compute_guideline(window)`으로 가이드라인 구간을 구해서(있으면) pending
   선택으로 채우고 그 구간에 맞춰 확대(`zoom_to_fit`) + seek. 없으면(distraction)
   window 전체 범위로 확대 + window 시작으로 seek.
5. `_missing_sensor_coverage()`로 이 구간에 없는 센서를 확인해 경고 배너
   표시/숨김.
6. `_refresh_draft_list()`.

### `_compute_guideline(window)`

drowsiness + `DistractionTaskWindow`면 `window.drowsiness_window`(시작 60초
전~시작), cognitive + `CognitiveTaskWindow`면 `window.start_ts`/`end_ts` 그대로.
그 외(distraction)는 `None` - 가이드라인 자체가 없어 라벨러가 처음부터 직접
구간을 정의해야 한다.

### `_missing_sensor_coverage(start_ts, end_ts)`

카메라는 7개 스트림 중 하나라도(대략적 범위, `first_t_sec`/`last_t_sec` 기준)
겹치면 있다고 판정. 오디오/IMU/워치/레이더는 `self.sensor_coverage`(페이지
로드 시 미리 계산된 세그먼트별 범위)를 이름별로 `range_overlaps_any()`로
개별 확인. 데이터 없는 센서 이름 목록을 반환(비어있으면 전부 있음).

(소스에 `return missing` 다음에 도달 불가능한 `return False`가 한 줄 남아있음
- 예전 리팩터링의 잔재로 보이며 실행에는 영향 없음.)

## 시작/끝점 지정, 가이드라인 리셋

- `_on_mark_start`/`_on_mark_end`: 구간 미리보기 한계 해제 후 현재 재생헤드
  위치를 pending 시작/끝으로 기록.
- `_on_reset_to_guideline`: `_compute_guideline()`으로 다시 계산(없으면 window
  전체 범위)해서 pending 선택을 되돌림.

## draft 저장/조회/수정/삭제

- `_on_save_draft`: pending 선택이 유효한지, 겹치는 draft가 없는지
  (`find_overlap`) 확인한 뒤 `draft_store.add_draft()`로 저장. `is_free_text_override`는
  별도로 설정 후 다시 `save()`(add_draft 안에서 한 번, 여기서 또 한 번 저장됨).
  `boundaries_locked=False`(distraction)면 pending 선택을 리셋해서 다음 서브
  구간을 바로 이어서 정의할 수 있게 함 - `boundaries_locked=True`는 리셋하지
  않음(가이드라인 값이 계속 남아있음).
- `_on_draft_item_clicked`: 목록 클릭 시 그 구간으로 확대+seek,
  `playback.set_playback_limit(draft.end_ts)`로 그 구간 끝에서 자동 정지하게
  설정(완료/미완료 구간 모두 클릭으로 내용 미리보기 가능, 수정/삭제 가능
  여부와는 무관).
- `_on_delete_draft`/`_on_edit_draft`: `draft_store.is_committed_and_present()`로
  커밋+디스크 존재를 확인해 커밋된 draft는 차단. 수정은 "불러와서 폼에 채운 뒤
  기존 걸 지우고, 라벨러가 값을 고쳐 다시 저장하면 새 draft로 대체"하는
  방식으로 구현된다(부분 업데이트가 아님).
- `_refresh_draft_markers`: 미완료 draft만 타임라인에 빨간 마커로 표시.
- `_refresh_draft_list`: `all_drafts_for_scenario()`(완료 포함 전체)에서 현재
  window에 속하는 것만 필터링해 목록에 채움, 완료된 것은 `[완료]` 접두어.

## 구간 미리보기 한계 해제 지점

`set_playback_limit(None)`(구간 미리보기 자동 정지 해제)이 호출되는 곳:
`_on_timeline_clicked`, `_on_video_panel_clicked`, `_load_task_window`,
`_on_mark_start`, `_on_mark_end`, `_on_reset_to_guideline`, `_step_frame`.
"이제 자유롭게 탐색/편집하겠다"는 신호가 되는 조작 전부에서 해제되도록
전수 점검된 목록.

## 최종 저장(export) 흐름

`_on_final_commit`:
1. 미완료 draft 목록을 모으고, 없으면 안내 후 종료. 확인 다이얼로그.
2. 각 draft에 대해 `source_window_id`로 원본 `TaskWindow`를 찾고, cognitive면
   `task_name`도 같이 job에 담는다(`jobs: list[(draft, cognitive_task_name,
   window)]`).
3. `_set_draft_controls_enabled(False)`로 draft 조작 버튼/window 콤보를 잠금
   (export 도중 draft_store/exporter를 동시에 건드리는 것 방지).
4. **공유 `self.exporter`를 그대로 안 쓰고**, `SegmentExporter(self.trial,
   self.exporter.session_dir)`로 이 배치 전용 독립 인스턴스를 새로 만든다 -
   세 시나리오 페이지가 하나의 `self.exporter`를 공유하는 구조라, 그대로
   백그라운드로 넘기면 다른 시나리오에서 동시에 "최종 저장"을 눌렀을 때 캐시/
   카운터를 두 스레드가 동시에 건드리는 경쟁 상태가 생길 수 있다
   (`SegmentNamer`가 디스크 스캔 기반이라 매번 새로 만들어도 번호는 안 꼬임).
5. `ExportWorker`를 만들어 4개 시그널(`progress`, `step_progress`,
   `finished_ok`, `failed`)을 연결하고 시작. `self._export_worker`에 보관해서
   실행 중에 GC되지 않게 함.

진행 상황 표시: `_export_done`/`_export_total`/`_export_step`을 갱신하며
`_update_export_status_text()`가 "최종 저장" 버튼 텍스트를 "저장 중...
(n/전체구간) {단계 메시지}"로 바꾼다.

완료/실패 처리: `_on_export_finished`/`_on_export_failed` 둘 다 그때까지
성공한 항목들에 대해 `draft_store.mark_committed()`를 호출한 뒤
`_finish_export_ui()`로 UI를 원상 복구(버튼 재활성화, 목록/진행상황 갱신)하고
결과 다이얼로그를 띄운다(성공/경고(seek 폴백 있었음)/실패 3가지 케이스).
