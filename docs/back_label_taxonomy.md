# `back/label_taxonomy.py`

`DMS_Actions.xlsx`(distraction 라벨 폼의 Area/Verb/Noun 드롭다운 목록 원본)를
파싱해서 `Area -> {verbs, nouns}` 구조로 변환한다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `load_dms_actions` | 앱 시작 시 xlsx 경로가 있으면 1회 로드해서 `self.areas`로 보관, `LabelingPage`에 전달 |
| `front/labeling_page.py` | `AreaTaxonomy` | 타입 힌트용 |
| `front/widgets/label_forms.py` | `AreaTaxonomy, OTHER_LABEL, area_names, verbs_for, nouns_for` | Area/Verb/Noun 드롭다운을 실제로 채우고 "기타" 옵션을 붙임 |

## xlsx 실측 구조

- A열 = Area 이름(병합된 것처럼 그 Area 블록의 첫 행에만 값이 있음)
- B열 = Verb 목록(Area 블록 안에서 세로로 나열)
- C열 = Noun 목록
- D열 = abstract noun(파싱 안 함, 참고용으로만 존재)
- 블록 사이에 숫자만 있는 요약 행이나 빈 행이 섞여 있을 수 있음

## `AreaTaxonomy` (dataclass)

`name`, `verbs: list[str]`, `nouns: list[str]`.

## `load_dms_actions(xlsx_path) -> list[AreaTaxonomy]`

`openpyxl`로 워크북의 첫 시트를 열어(`data_only=True` - 수식이 아니라 계산된 값을
읽음), 2행부터(1행은 헤더) 순회한다. A열에 값이 있으면 새 `AreaTaxonomy`를
시작(`current`), 그 이후 행들은 B/C열 값을 `current.verbs`/`current.nouns`에
중복 없이 추가한다. A열이 비어있는 행은 직전에 시작된 Area 블록에 계속
포함되는 것으로 처리된다(병합 셀을 흉내).

## 드롭다운 채우기 헬퍼

- `area_names(areas)`: 모든 Area 이름 + `"기타"`.
- `verbs_for(areas, area_name)` / `nouns_for(areas, area_name)`: 해당 Area의
  verb/noun 목록 + `"기타"`. Area를 못 찾으면 `["기타"]`만 반환.

`"기타"`(자유 서술) 옵션은 이 파일이 목록 끝에 붙여주기만 하고, 실제로 그
옵션을 골랐을 때 텍스트 입력창을 보여주는 처리는 `front/widgets/label_forms.py`가
담당한다. 그 자유 서술을 썼는지 여부는 `back/models.py`의
`LabelDraft.is_free_text_override`에 필드별로 기록된다.
