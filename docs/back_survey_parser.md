# `back/survey_parser.py`

트라이얼 폴더의 `survey/*.json`(실험 프로토콜 진행 중 자동 기록된 설문 응답)을
파싱해서 `TaskWindow` 리스트를 만든다. 라벨러가 만드는 게 아니라 이 모듈이
자동으로 만들어 타임라인에 미리 그려주는 마커의 원천.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `SurveyParser` | 세션 선택 시 `parse_all()`을 호출해 시나리오별 `_task_windows_by_scenario` 딕셔너리를 채움 |

## survey json의 `section_name` 종류

- `intro`: 피험자 기본 정보. `TaskWindow`로 변환 안 됨(`get_intro()`로 원본
  payload만 조회 가능).
- `cognitive_before_driving`: `pre_nback1~3`, `pre_cbt1~3`.
- `cognitive_after_driving`: `post_nback1~3`, `post_cbt1~3`.
- `driving`: distraction task window(+ drowsiness 서브구간이 그 안에 내장).

**모듈 docstring에 남아있는 메모**: "`cognitive_after_driving` 실제 파일을 아직
못 봤어서 before와 동일 스키마를 가정한다"는 문구가 있는데, 이 세션 안에서 실제
`cognitive_after_driving` 파일을 확인했다(`payload.cognitive_task_results`
스키마는 실제로 동일했음. 단, 그 실제 파일 자체에 `cognitive_before_driving`의
결과가 그대로 중복 포함되어 12개(정상은 6개)가 들어있는 수집 파이프라인 버그가
있었음 - 코드가 아니라 해당 트라이얼의 survey json 파일을 직접 수정해서 해결,
파서 코드는 그대로 둠). docstring 자체는 갱신되지 않은 상태로 남아있다.

## `SurveyParser.__init__(survey_dir)` / `_load_all()`

`survey_dir` 아래 모든 `*.json`을 읽어서 `section_name` 필드 기준으로
`self._sections: dict[str, list[dict]]`에 모아둔다. 같은 `section_name`의 파일이
여러 개 있을 수 있다는 전제로 리스트에 담지만, 실제로 파싱 메서드들
(`_parse_cognitive_section`, `parse_distraction_windows`)은 `docs[0]`(정렬 순서상
가장 먼저 발견된 파일)만 사용한다 - 같은 섹션 파일이 여러 개면 첫 번째 이후는
읽히지 않는다.

## `parse_cognitive_windows()` / `_parse_cognitive_section(section_name, phase)`

`cognitive_before_driving`(`phase="pre"`)과 `cognitive_after_driving`
(`phase="post"`)을 각각 파싱해서 합친다. 한 섹션 안에서는
`payload.cognitive_task_results` 리스트를 순서대로 순회하며, `task_type`
("nback"|"cbt")별로 등장 순서대로 1부터 번호를 매겨 `task_name`을
`f"{phase}_{task_type}{번호}"`로 조합한다(예: `pre_nback1`, `post_cbt3`). 이
번호 부여는 리스트 순서만 보고 매기므로, 만약 한 섹션의 `cognitive_task_results`
안에 기대보다 많은 항목이 들어있으면(위에서 언급한 실제 버그 사례처럼) 번호가
3을 넘어 4, 5, 6까지 매겨질 수 있다 - 이 함수 자체엔 "task_type당 3개까지만"
같은 검증/제한이 없다.

`extra=item`으로 원본 json 항목 전체를 `TaskWindow.extra`에 보존한다 -
`mental_demand`, `kss_score` 등 라벨 필드로 안 쓰는 값도 최종 export 시
`annotation.json`의 `survey_extra`로 남는다(`back/segment_exporter.py`).

## `parse_distraction_windows()`

`driving` 섹션의 `payload.driving_task_results` 리스트를 순서대로 순회하며
`window_id`를 `f"driving_task_{i}"`(1부터)로 부여한다. `distraction_task_id`,
`distraction_task_text`(라벨러에게 보여줄 지시문), `kss_score`/`kss_label`을
`DistractionTaskWindow`의 필드로 옮긴다 - `kss_score`/`kss_label`은 이 window가
나중에 `drowsiness` 시나리오에서도 재사용될 때(`DistractionTaskWindow.drowsiness_window`)
같이 쓰인다.

## `parse_all()`

`{"cognitive": [...], "distraction": [...]}` 딕셔너리를 반환. `drowsiness`용
window는 따로 없다 - `front/main_window.py`가 `parsed["distraction"]`을
`Scenario.DROWSINESS` 키에도 그대로 재사용한다(drowsiness 구간이 독립 survey
섹션이 아니라 distraction task window에 내장된 서브구간이기 때문).

## `_parse_dt(s)`

`datetime.fromisoformat(s)`. survey json의 시각 문자열에 시간대 오프셋이 없어서
(예: `"2026-07-31T14:45:28.425247"`), 결과 `datetime`도 시간대 정보 없는(naive)
객체가 된다 - `back/models.py`의 `TaskWindow.start_ts`/`end_ts` 프로퍼티가 이
naive datetime에 `.timestamp()`를 호출할 때, 그 결과가 실행 중인 시스템의
로컬 시간대에 좌우된다(`docs/back_models.md` 참고).
