# `back/draft_store.py`

라벨 draft(확정 전 작업 중 상태)를 트라이얼별 JSON 파일 하나에 저장/불러오는
저장소. 최종 저장(export) 전까지 라벨러가 만들고 수정하는 모든 타임스탬프+라벨
쌍이 이 파일을 거친다.

draft 파일 경로는 원본 raw 데이터 폴더 바깥, `<home_dir>/.labeling_drafts/
{trial_folder_name}.json`이다(`front/main_window.py`가 경로를 조합) - 원본
데이터 폴더를 건드리지 않기 위함.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `DraftStore` | 세션 선택 시 `self._draft_store` 하나를 만들어 모든 시나리오 페이지가 공유 |
| `front/labeling_page.py` | `DraftStore` | draft 생성/조회/삭제/커밋 표시까지 화면의 거의 모든 draft 관련 동작이 이 인스턴스를 거침 |

## `DraftStore.__init__(draft_path)` / `_load()` / `save()`

생성 시 파일이 있으면 즉시 로드(`self.drafts: dict[draft_id, LabelDraft]`).
`_load()`는 JSON의 `scenario` 문자열을 `Scenario` enum으로 변환한 뒤
`LabelDraft(**d)`로 역직렬화한다. `save()`는 반대로 `dataclasses.asdict()` +
`scenario.value`로 직렬화해서 파일 전체를 다시 쓴다(부분 업데이트가 아니라
매번 전체 재작성) - `add_draft`/`update_draft`/`remove_draft`/`mark_committed`
전부 끝에 `self.save()`를 호출해서, draft 상태 변화가 항상 즉시 디스크에
반영된다(다른 task로 전환하거나 앱을 꺼도 안전).

## draft 조회 메서드 3종의 차이

- `drafts_for_scenario(scenario)`: **미완료(`not d.committed`)** draft만, 시작
  시각순. "작업 중인 구간들" 목록의 대상이자, `_on_final_commit`이 export할
  draft 목록을 뽑을 때도 이 메서드를 쓴다(이미 커밋된 걸 다시 export 대상에
  올리지 않기 위해 - `segment_dir`이 사라졌어도 여기서는 걸러지지 않고 그냥
  제외됨, 아래 `is_committed_and_present`와는 별개 기준).
- `all_drafts_for_scenario(scenario)`: 커밋 여부 상관없이 전부, 시작 시각순.
  "작업 중인 구간들" 목록 표시용(완료된 것도 이력으로 계속 보여주기 위해).
- `committed_window_ids(scenario)`: `source_window_id`가 있는 draft 중
  `is_committed_and_present()`가 참인 것들의 `source_window_id` 집합. 상단
  진행 상황 배너(`_refresh_progress_label`)가 "몇 개 task window가 완료됐는지"
  셀 때 사용.

## `is_committed_and_present(draft)`

"완료"로 볼지 판단하는 유일한 기준 메서드. `draft.committed`가 `False`면 바로
`False`. `True`이고 `segment_dir`이 기록돼 있으면 `Path(segment_dir).exists()`까지
확인해서, 라벨러가 결과 폴더를 수동으로 지웠으면 `False`를 반환한다.
`segment_dir`이 없는(이 필드가 생기기 전에 커밋된) 옛 기록은 디스크 확인
방법이 없어 그대로 완료로 인정한다.

`front/labeling_page.py`에서 "완료"를 판단하는 세 곳(진행 상황 배너의
`committed_window_ids`, 목록의 `[완료]` 표시, 수정/삭제 버튼 차단)이 전부 이
메서드(또는 이 메서드를 쓰는 `committed_window_ids`)를 거친다 - 한 곳만 디스크
확인을 하고 나머지 두 곳은 `draft.committed` 플래그만 직접 보던 시기가 있었고,
그때는 결과 폴더를 지워도 목록의 `[완료]` 표시와 수정/삭제 차단이 풀리지 않는
불일치가 있었다.

## `find_overlap(scenario, start_ts, end_ts, exclude_draft_id=None)`

같은 시나리오의 **미완료** draft들 중 주어진 시간 범위와 겹치는 첫 번째 draft를
찾는다(`d.start_ts < end_ts and start_ts < d.end_ts` 조건). 라벨러가 새 구간을
저장하기 전에 이미 겹치는 draft가 있는지 확인하는 용도
(`front/labeling_page.py`의 "구간 저장" 버튼 핸들러). 커밋된 draft는 검사
대상에서 제외된다 - 커밋된 구간은 어차피 수정 불가라 겹침 검사의 의미가
없다는 전제.

## `mark_committed(draft_id, segment_dir=None)`

`SegmentExporter.export_draft()`가 성공적으로 끝난 뒤에만 호출된다(export
자체는 `back/` 계층에서 이 메서드를 직접 호출하지 않음 - `front/labeling_page.py`가
`ExportWorker`의 완료 시그널을 받은 메인 스레드에서 호출). `committed=True`로
바꾸고, `segment_dir`이 주어졌으면 같이 기록한다.
