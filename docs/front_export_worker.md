# `front/export_worker.py`

"최종 저장"(draft들을 실제로 잘라 내보내는 export) 배치를 백그라운드 스레드에서
돌리는 워커.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page.py` | `ExportWorker` | "최종 저장" 버튼을 누르면 이 워커를 만들어 시작, 진행률/완료/실패 시그널을 UI에 반영 |

## 왜 필요한지

`SegmentExporter.export_draft()`는 카메라 프레임 재인코딩 때문에 구간 하나당
수 초~수십 초씩 걸릴 수 있다(`back/segment_exporter.py` 참고). 메인(UI)
스레드에서 그대로 호출하면 그동안 Qt 이벤트 루프가 멈춰서 OS가 "응답 없음"을
띄운다 - `QThread`로 분리해서 export가 도는 동안에도 UI가 계속 반응하게 하고,
진행상황/완료/실패는 시그널로 메인 스레드에 전달한다.

## 시그널

- `progress(int, int)`: (완료된 draft 개수, 전체 개수) - 배치 안에서 draft가
  하나 끝날 때마다.
- `step_progress(str)`: draft 하나 안에서 지금 어느 스트림/단계를 내보내는
  중인지(`SegmentExporter.export_draft`의 `on_progress` 콜백을 그대로 여기
  emit으로 연결). `run()`에서 `on_progress=self.step_progress.emit`로 직접
  넘긴다 - `back/` 계층은 Qt에 의존하면 안 되므로, `back/`은 평범한 콜러블만
  받고 이 워커가 Qt 시그널로 다시 감싼다.
- `finished_ok(list, list)`: `([(draft_id, segment_dir_str), ...],
  export_warnings)` - 배치 전체가 성공적으로 끝났을 때.
- `failed(list, str)`: `(실패 전까지 완료된 [(draft_id, segment_dir_str), ...],
  에러 메시지)` - 배치 도중 예외가 나면, 그 전까지 이미 성공한 항목들을 잃지
  않고 같이 전달한다(부분 성공 상태를 메인 스레드가 반영할 수 있도록).

## `__init__(exporter, jobs, parent=None)`

`jobs: list[tuple[LabelDraft, cognitive_task_name|None, source_window|None]]`.
`exporter`는 `front/labeling_page.py`가 "최종 저장"을 누를 때마다 새로 만든
`SegmentExporter` 인스턴스(동시성 문제 회피, `docs/back_segment_exporter.md`
"동시성" 참고).

## `run()`

`self.exporter.export_warnings = []`로 먼저 초기화한 뒤, `jobs`를 순서대로
`export_draft()` 호출. 각 draft가 끝날 때마다 `(draft_id, segment_dir)`을
`committed` 리스트에 쌓고 `progress` emit. 전부 끝나면 `finished_ok(committed,
self.exporter.export_warnings)` emit(warnings는 `_write_video_cut`이 seek
폴백을 했을 경우 등에 쌓인 것).

**`DraftStore.mark_committed()`는 이 워커 안에서 호출하지 않는다** - 메인
스레드가 `finished_ok`/`failed` 시그널을 받은 뒤에 몰아서 호출한다
(`front/labeling_page.py`의 `_on_export_finished`/`_on_export_failed`). draft_store
파일 I/O를 백그라운드 스레드와 메인 스레드가 동시에 건드리지 않게 하기 위한
분리.
