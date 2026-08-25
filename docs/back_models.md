# `back/models.py`

라벨링 도메인의 기본 데이터 타입 정의. Qt에 의존하지 않는 순수 `@dataclass` 모음이라
`back/` 어디서든, 그리고 `front/`에서도 그대로 가져다 쓴다. 이 파일은 다른 `back/`
모듈을 하나도 import하지 않는 최하위 계층 — 프로젝트 전체 의존성 그래프의 뿌리.

## 이 파일을 가져다 쓰는 곳 (import 관계)

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `back/survey_parser.py` | `Scenario, TaskWindow, DistractionTaskWindow, CognitiveTaskWindow` | survey json을 파싱해서 TaskWindow 리스트를 만드는 쪽 |
| `back/draft_store.py` | `LabelDraft, Scenario` | draft를 JSON에 저장/복원할 때 `LabelDraft(**d)`로 역직렬화 |
| `back/segment_exporter.py` | `Scenario, LabelDraft, TaskWindow` | 시나리오별 세그먼트 번호 카운터, export 시 draft를 읽어 자름 |
| `front/labeling_page.py` | `Scenario, TaskWindow, DistractionTaskWindow, CognitiveTaskWindow, LabelDraft` | 화면 전체가 이 타입들을 기준으로 동작(아래 "실제 쓰이는 방식" 참고) |
| `front/main_window.py` | `Scenario` | 시나리오별 페이지 캐시 딕셔너리의 키로 사용 |
| `front/export_worker.py` | `LabelDraft, TaskWindow` | export 백그라운드 스레드의 타입 힌트용 |

## `Scenario` (str Enum)

```python
class Scenario(str, Enum):
    DISTRACTION = "distraction"
    DROWSINESS = "drowsiness"
    COGNITIVE = "cognitive"
```

`str`을 상속해서 `Scenario.DISTRACTION == "distraction"`이 참이 되고, `f"{scenario.value}"`
없이 문자열 위치에 바로 써도(예: 폴더명 조합, JSON 직렬화) 동작한다. 이 값 자체가
`session_dir/{scenario}/` 폴더명, `annotations/{scenario}.csv` 파일명, 세그먼트 이름
접두어로 그대로 쓰인다.

세 시나리오는 **세그멘테이션 자유도가 서로 다르다**:
- `DISTRACTION`: 라벨러가 완전히 자유롭게 구간을 나눔. 세그먼트 번호는 독립 카운터
  (`SegmentNamer`, `back/segment_exporter.py`).
- `DROWSINESS`: survey json에서 자동 계산된 구간(`DistractionTaskWindow.drowsiness_window`)이
  기본값이지만 라벨러가 프레임 단위로 조정 가능. 세그먼트 번호도 독립 카운터.
- `COGNITIVE`: 자동 계산된 구간 그대로, 번호 카운터 없이 고정 이름(`pre_nback1~3`,
  `pre_cbt1~3`, `post_nback1~3`, `post_cbt1~3`)만 사용.

## `TaskWindow` / `DistractionTaskWindow` / `CognitiveTaskWindow`

**survey json에서 자동으로 파싱되어 타임라인에 "미리" 그려지는 구간.** 라벨러가
만드는 게 아니라 실험 프로토콜 기록(설문 응답 json)에서 나온다. 실제 생성은
`back/survey_parser.py`의 `SurveyParser.parse_cognitive_windows()` /
`parse_distraction_windows()`가 담당 — 이 파일(`models.py`)엔 껍데기(dataclass)만
있고 생성 로직은 없다.

### 공통 필드 (`TaskWindow`)

- `window_id`: 내부 식별용 문자열. `driving_task_1`, `cognitive_pre_nback1` 같은 형태.
  `LabelDraft.source_window_id`가 이 값을 참조해서 "이 draft가 어느 task window에서
  파생됐는지"를 기록한다.
- `start_time`/`end_time`: `datetime` 객체. **시간대 정보가 없는(naive) datetime**이다 -
  survey json의 ISO 문자열(`"2026-07-31T14:45:28.425247"`, 오프셋 없음)을
  `datetime.fromisoformat()`으로 그대로 파싱한 결과라서다.
- `start_ts`/`end_ts` (프로퍼티): `start_time.timestamp()` / `end_time.timestamp()`.
  **여기서 시간대 이슈가 발생한다** - naive datetime의 `.timestamp()`는 파이썬이
  "지금 이 프로그램이 돌고 있는 시스템의 로컬 시간대"를 그대로 써서 epoch로 변환한다.
  이 프로젝트는 지금까지 전부 KST로 설정된 머신에서만 실행돼서 우연히 문제가 없었지만,
  다른 시간대의 머신에서 돌리면 이 값이 실제 센서 t_sec 축과 어긋난다. 코드 어디에도
  명시적인 `Asia/Seoul` 지정은 없다 (`back/survey_parser.py:_parse_dt` 참고).
- `extra`: 원본 json 필드를 통째로 보존하는 dict. `kss_score`, `task_text` 등 -
  최종 export 시 `annotation.json`의 `survey_extra`로 그대로 옮겨져서(`segment_exporter.py`)
  라벨 필드로 안 쓰는 원본 정보도 결과물에 남는다.

### `DistractionTaskWindow`

`distraction_task_id`, `distraction_task_text`(라벨러에게 보여줄 지시문 힌트),
`kss_score`/`kss_label`(drowsiness 시나리오에서 재사용)을 추가로 갖는다.

`drowsiness_window` 프로퍼티:
```python
@property
def drowsiness_window(self) -> tuple[datetime, datetime]:
    return (self.start_time - timedelta(seconds=60), self.start_time)
```
"질문 시작(`start_time`) 이전 정확히 60초"를 반환한다 - drowsiness 시나리오의
가이드라인 구간이 이 값 그대로다(`front/labeling_page.py:_compute_guideline`가 호출).
60초로 고정한 이유는 설문에 구두로 답하는 목소리가 그 앞뒤 오디오에 섞여 들어가지
않게 하려는 의도(라벨링 정책으로 확정된 값, 라벨러가 조정 못 함 - 단, 이 60초짜리
기본 구간 자체는 프레임 단위로 미세 조정 가능).

`front/main_window.py`에서 drowsiness 시나리오의 `task_windows`는 별도로 파싱하지 않고
distraction과 **같은 리스트를 그대로 재사용**한다(`parsed["distraction"]`) - drowsiness
구간이 독립된 survey 섹션이 아니라 distraction task window에 내장된 서브구간이기
때문. `front/labeling_page.py`가 `isinstance(window, DistractionTaskWindow)`로
분기해서 시나리오에 따라 `drowsiness_window`를 쓸지 원래 구간을 쓸지 결정한다.

### `CognitiveTaskWindow`

`task_name`(`pre_nback1` 같은 고정 이름 - 이게 최종 export 폴더명이 됨),
`task_type`("nback"|"cbt"), `difficulty`("easy"|"normal"|"hard"), `phase`("pre"|"post")를
추가로 갖는다. `task_name`은 `survey_parser.py`가 `f"{phase}_{task_type}{순번}"`으로
조합해서 만든다(순번은 같은 phase 안에서 task_type별로 1부터).

## `LabelDraft`

**라벨러가 실제로 확정하기 전까지 임시로 들고 있는 작업 중 라벨.** "최종 저장" 전까지는
`DraftStore`(로컬 JSON 파일, `back/draft_store.py`)에만 존재하고 실제 센서 파일은
전혀 잘리지 않는다 - Draft/Export 분리 원칙에서 이 상태를 표현하는 타입.

- `draft_id`: uuid 문자열. `DraftStore.drafts` dict의 키.
- `start_ts`/`end_ts`: **여기는 `TaskWindow`와 달리 처음부터 float(unix epoch)다** -
  `datetime`을 거치지 않고 `PlaybackController`가 다루는 절대시각을 그대로 저장한다.
  export 시 `SegmentExporter`가 이 두 값을 그대로 각 센서의
  `time_range_to_file_ranges(start_ts, end_ts)` 호출에 넘긴다 - t_sec이 "진실의
  근원"이라는 원칙이 이 필드에 딱 반영돼 있다(프레임 인덱스는 저장 안 함, 매번 새로
  계산).
- `source_window_id`: 이 draft가 어느 `TaskWindow.window_id`에서 파생됐는지(없을 수도
  있음 - distraction은 자유 분할이라 하나의 window에서 여러 draft가 나올 수 있음).
  `DraftStore.committed_window_ids()`가 "이 window는 완료됐다"를 판단할 때 이 필드로
  묶어서 센다.
- `label_fields`: 시나리오별로 내용이 다른 라벨 값 dict(위 주석 예시 참고). 실제 폼
  구성은 `front/widgets/label_forms.py`가 만들고, 여기엔 그 결과 dict만 저장된다.
- `is_free_text_override`: 필드별로 "기타" 자유 서술을 썼는지 표시 - `label_forms.py`의
  "기타" 탈출구 기능과 짝을 이룸.
- `committed`: 최종 export 완료 여부. **주의**: 이 플래그만 보고 "완료"를 판단하면
  안 되는 경우가 있다 - 아래 `segment_dir` 설명 참고.
- `segment_dir`: 최종 export된 실제 폴더 경로(`committed=True`일 때만 값 있음).
  `DraftStore.is_committed_and_present(draft)`가 `committed`뿐 아니라
  `Path(segment_dir).exists()`까지 확인해서, 라벨러가 결과 폴더를 수동으로 지워도
  "완료"로 잘못 남아있지 않게 한다(이 필드가 생기기 전에 커밋된 옛 기록은 확인할
  방법이 없어서 그대로 신뢰 - 하위호환). 한때 `committed` 플래그만 보고 판단하는
  곳이 세 군데(진행 배너, `[완료]` 표시, 수정/삭제 차단) 중 하나만 디스크 확인을
  거치는 불일치가 있었고, `is_committed_and_present()`로 통일해서 고쳤다.

## 실제로 어떻게 쓰이는지 (front/labeling_page.py 기준 흐름)

1. `MainWindow._on_session_selected()`가 `SurveyParser.parse_all()`로 `TaskWindow` 리스트를
   만들어 시나리오별 dict(`_task_windows_by_scenario`)에 저장.
2. 라벨러가 시나리오를 고르면 `LabelingPage`가 그 리스트를 받아 `TimelineWidget`에
   마커로 그림(`_load_task_window`가 매번 새로 그림).
3. 라벨러가 시작/끝점을 찍고 라벨 폼을 채운 뒤 "구간 저장"을 누르면 `LabelDraft`
   인스턴스가 만들어져 `DraftStore.add_draft()`로 들어감(즉시 JSON 저장, 아직
   `committed=False`).
4. "최종 저장"을 누르면 `ExportWorker`(백그라운드 스레드)가 `SegmentExporter.export_draft(draft)`를
   호출 - 이때 `draft.start_ts`/`end_ts`가 각 센서의 시간 인덱스에 그대로 전달되어
   실제 파일이 잘림. 성공하면 `DraftStore.mark_committed(draft_id, segment_dir)`가
   호출되어 `committed=True` + `segment_dir` 기록.
