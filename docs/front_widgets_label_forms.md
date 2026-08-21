# `front/widgets/label_forms.py`

시나리오별(distraction/drowsiness/cognitive) 라벨 입력 폼 3종 + 공통 위젯
`ComboWithOther`. `back/label_taxonomy.py`가 제공하는 Area/Verb/Noun 목록을
받아 드롭다운을 채운다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/labeling_page.py` | `DistractionLabelForm, DrowsinessLabelForm, CognitiveLabelForm` | 시나리오에 맞는 폼 하나를 만들어 `self.label_form`으로 보관, 값 읽기(`get_label_fields`)/쓰기(`load_values`)를 draft 저장/수정 시 호출 |

## `ComboWithOther`

카테고리형 필드 공통 패턴: 드롭다운 + `"기타"`(`OTHER_LABEL`, `back/
label_taxonomy.py`에서 가져옴) 선택 시 자유 서술 입력란(`QLineEdit`)이
나타난다.

- `value() -> (값, 자유서술_여부)`: 드롭다운이 `"기타"`가 아니면 그 텍스트
  그대로, `"기타"`면 자유 서술 입력란의 텍스트와 함께 `True` 반환.
- `set_value(value)`: 반대 방향(기존 draft를 폼에 되돌려 채울 때) - 드롭다운
  옵션 중에 그 값이 있으면 그걸 선택, 없으면 `"기타"`를 선택하고 자유 서술
  입력란에 그 값을 채운다.
- `set_options(options)`: 드롭다운 옵션 자체를 갈아끼움(Area가 바뀌면
  Verb/Noun 옵션이 바뀌어야 하므로) - `blockSignals`로 감싸서 옵션을 바꾸는
  동안 `currentTextChanged`가 불필요하게 발생하지 않게 함.

## `ROAD_CONDITIONS`/`WEATHER_OPTIONS`

도로상황/날씨 옵션은 PDF 목업에서 본 예시 기반의 placeholder 목록(파일
docstring에 명시) - 실제 표준 옵션 목록이 확정되면 이 두 리스트만 교체하면
된다.

## `DistractionLabelForm(areas)`

필드: 지시문 힌트(읽기 전용 표시, `set_hint`), Area(`ComboWithOther`), Verb,
Verb-세부(자유 텍스트), Noun, Noun-세부(자유 텍스트), 도로상황, 날씨.

Area를 바꾸면 `_on_area_changed`가 `verbs_for`/`nouns_for`(`back/
label_taxonomy.py`)로 그 Area에 맞는 Verb/Noun 옵션을 다시 채운다 -
Area→Verb/Noun 계층 관계가 이 폼 안에서 구현된다.

`get_label_fields() -> (fields, overrides)`: `fields`는 `LabelDraft.label_fields`에
그대로 들어갈 dict(`area`, `verb`, `noun`, `verb_detail`, `noun_detail`,
`road_condition`, `weather`), `overrides`는 `LabelDraft.is_free_text_override`에
들어갈 dict(필드별로 "기타" 자유 서술을 썼는지).

`load_values(fields, overrides)`: 기존 draft를 수정할 때 폼에 값을 되돌려
채운다(`get_label_fields`의 역방향) - Area를 먼저 설정해야 Verb/Noun 옵션이
그에 맞게 갱신된 뒤에 Verb/Noun 값을 설정할 수 있으므로 순서가 중요하다.

## `DrowsinessLabelForm`

필드: KSS 점수(읽기 전용 `QLabel`), 도로상황, 날씨. KSS 점수는 survey json에서
파싱된 값을 `set_prefill_kss(kss_score)`로 그대로 표시만 하고 라벨러가 바꾸는
입력 필드가 아니다(과거엔 `QSpinBox`였는데, "어차피 파싱값이니 고정 표시로
바꿔달라"는 요청으로 `QLabel`로 교체됨).

## `CognitiveLabelForm`

필드: 태스크(읽기 전용, `task_type` 표시), 난이도(읽기 전용, `set_prefill`로
채워짐), 날씨. 난이도도 KSS 점수와 같은 이유로 읽기 전용 `QLabel`.

`get_label_fields()`의 `overrides["difficulty"]`는 항상 `False`로 고정 -
난이도는 애초에 드롭다운/자유서술 입력 필드가 아니라 survey json 값을 그대로
표시하는 필드라 "기타" 개념 자체가 없다.

## 세 폼이 공유하는 인터페이스

`LabelingPage`는 세 폼을 다형적으로 다룬다 - `set_hint`/`set_prefill_kss`/
`set_prefill`은 시나리오별로 다르게 호출되지만(`_load_task_window`가
`isinstance` 분기), `get_label_fields()`/`load_values()`는 세 폼 다 같은
시그니처로 구현돼 있어서 호출부(`_on_save_segment`, `_on_edit_draft`)가
시나리오를 구분하지 않고 `self.label_form.get_label_fields()`/
`self.label_form.load_values(...)`를 그대로 호출할 수 있다.
