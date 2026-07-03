"""
DMS_Actions.xlsx 파싱 -> Area -> {verbs: [...], nouns: [...]} 구조.

xlsx 실측 구조:
  A열 = Area 이름 (병합된 것처럼 첫 행에만 존재)
  B열 = Verb 목록 (Area 블록 내에서 세로로 나열)
  C열 = Noun 목록
  D열 = abstract noun (사용 안 함, 참고용)
  중간중간 숫자만 있는 행(개수 요약)과 빈 행으로 블록이 구분됨

모든 카테고리 드롭다운은 "기타" 옵션 + 자유 서술 입력을 함께 지원해야 하므로,
여기서는 목록만 제공하고 "기타" 처리는 라벨링 UI/모델(LabelDraft.is_free_text_override) 쪽에서 담당.
"""
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

OTHER_LABEL = "기타"


@dataclass
class AreaTaxonomy:
    name: str
    verbs: list = field(default_factory=list)
    nouns: list = field(default_factory=list)


def load_dms_actions(xlsx_path: str) -> list[AreaTaxonomy]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]

    areas: list[AreaTaxonomy] = []
    current: AreaTaxonomy = None

    rows = list(ws.iter_rows(min_row=2, values_only=True))  # 1행은 헤더
    for row in rows:
        area_cell, verb_cell, noun_cell = row[0], row[1], row[2]

        if area_cell:  # 새 Area 블록 시작
            current = AreaTaxonomy(name=str(area_cell).strip())
            areas.append(current)

        if current is None:
            continue

        if isinstance(verb_cell, str) and verb_cell.strip():
            v = verb_cell.strip()
            if v not in current.verbs:
                current.verbs.append(v)
        if isinstance(noun_cell, str) and noun_cell.strip():
            n = noun_cell.strip()
            if n not in current.nouns:
                current.nouns.append(n)

    return areas


def area_names(areas: list[AreaTaxonomy]) -> list[str]:
    return [a.name for a in areas] + [OTHER_LABEL]


def verbs_for(areas: list[AreaTaxonomy], area_name: str) -> list[str]:
    for a in areas:
        if a.name == area_name:
            return a.verbs + [OTHER_LABEL]
    return [OTHER_LABEL]


def nouns_for(areas: list[AreaTaxonomy], area_name: str) -> list[str]:
    for a in areas:
        if a.name == area_name:
            return a.nouns + [OTHER_LABEL]
    return [OTHER_LABEL]
