"""
시나리오별 라벨 입력 폼.

공통 패턴: 카테고리형 필드는 드롭다운 + "기타" 선택 시 자유 서술 입력란이
나타남 (OTHER_LABEL = "기타", label_taxonomy.py에서 가져옴).

도로상황/날씨 옵션은 PDF 목업에서 본 예시("위험상황 - 전방 끼어들기", "흐림")
기반의 placeholder 목록입니다. 실제 표준 옵션 목록이 있으면 ROAD_CONDITIONS/
WEATHER_OPTIONS만 교체하면 됩니다.
"""
import sys
from pathlib import Path

from back.label_taxonomy import AreaTaxonomy, OTHER_LABEL, area_names, verbs_for, nouns_for

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QLineEdit
)

ROAD_CONDITIONS = ["일반 주행", "위험상황 - 전방 끼어들기", "위험상황 - 급정거",
                    "정체 구간", "교차로", OTHER_LABEL]
WEATHER_OPTIONS = ["맑음", "흐림", "비", "야간", OTHER_LABEL]


class ComboWithOther(QWidget):
    """드롭다운 + '기타' 선택 시 자유 서술 입력란이 나타나는 공통 위젯."""

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.combo = QComboBox()
        self.combo.addItems(options)
        layout.addWidget(self.combo)

        self.other_input = QLineEdit()
        self.other_input.setPlaceholderText("직접 입력")
        self.other_input.setVisible(False)
        layout.addWidget(self.other_input)

        self.combo.currentTextChanged.connect(self._on_change)

    def _on_change(self, text: str):
        self.other_input.setVisible(text == OTHER_LABEL)

    def set_options(self, options: list[str]):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(options)
        self.combo.blockSignals(False)
        self.other_input.setVisible(False)

    def value(self) -> tuple[str, bool]:
        """(값, 자유서술_여부) 반환."""
        text = self.combo.currentText()
        if text == OTHER_LABEL:
            return self.other_input.text().strip(), True
        return text, False

    def set_value(self, value: str):
        idx = self.combo.findText(value)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        else:
            self.combo.setCurrentText(OTHER_LABEL)
            self.other_input.setText(value)


# ------------------------------------------------------------------
class DistractionLabelForm(QWidget):
    def __init__(self, areas: list[AreaTaxonomy], parent=None):
        super().__init__(parent)
        self.areas = areas

        layout = QFormLayout(self)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addRow("지시문 힌트", self.hint_label)

        self.area_field = ComboWithOther(area_names(areas))
        layout.addRow("영역(Area)", self.area_field)

        self.verb_field = ComboWithOther([OTHER_LABEL])
        layout.addRow("동사(Verb)", self.verb_field)
        self.verb_detail = QLineEdit()
        layout.addRow("동사-세부", self.verb_detail)

        self.noun_field = ComboWithOther([OTHER_LABEL])
        layout.addRow("명사(Noun)", self.noun_field)
        self.noun_detail = QLineEdit()
        layout.addRow("명사-세부", self.noun_detail)

        self.road_field = ComboWithOther(ROAD_CONDITIONS)
        layout.addRow("도로상황", self.road_field)

        self.weather_field = ComboWithOther(WEATHER_OPTIONS)
        layout.addRow("날씨", self.weather_field)

        self.area_field.combo.currentTextChanged.connect(self._on_area_changed)
        self._on_area_changed(self.area_field.combo.currentText())

    def _on_area_changed(self, area_name: str):
        self.verb_field.set_options(verbs_for(self.areas, area_name))
        self.noun_field.set_options(nouns_for(self.areas, area_name))

    def set_hint(self, text: str):
        self.hint_label.setText(text)

    def get_label_fields(self) -> tuple[dict, dict]:
        area, area_other = self.area_field.value()
        verb, verb_other = self.verb_field.value()
        noun, noun_other = self.noun_field.value()
        road, road_other = self.road_field.value()
        weather, weather_other = self.weather_field.value()
        fields = {
            "area": area, "verb": verb, "noun": noun,
            "verb_detail": self.verb_detail.text().strip(),
            "noun_detail": self.noun_detail.text().strip(),
            "road_condition": road, "weather": weather,
        }
        overrides = {
            "area": area_other, "verb": verb_other, "noun": noun_other,
            "road_condition": road_other, "weather": weather_other,
        }
        return fields, overrides

    def load_values(self, fields: dict, overrides: dict):
        """기존 draft를 수정할 때 폼에 값을 되돌려 채움 (get_label_fields의 역방향)."""
        self.area_field.set_value(fields.get("area", ""))  # verb/noun 옵션이 area 기준으로 갱신됨
        self.verb_field.set_value(fields.get("verb", ""))
        self.noun_field.set_value(fields.get("noun", ""))
        self.verb_detail.setText(fields.get("verb_detail", ""))
        self.noun_detail.setText(fields.get("noun_detail", ""))
        self.road_field.set_value(fields.get("road_condition", ""))
        self.weather_field.set_value(fields.get("weather", ""))


# ------------------------------------------------------------------
class DrowsinessLabelForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)

        # survey json에서 파싱된 값 그대로 - 라벨러가 바꿀 필요 없어서 고정 표시만 함
        self.kss_label = QLabel("")
        layout.addRow("KSS 점수", self.kss_label)

        self.road_field = ComboWithOther(ROAD_CONDITIONS)
        layout.addRow("도로상황", self.road_field)

        self.weather_field = ComboWithOther(WEATHER_OPTIONS)
        layout.addRow("날씨", self.weather_field)

    def set_prefill_kss(self, kss_score: int | None):
        self.kss_label.setText(str(kss_score) if kss_score is not None else "")

    def get_label_fields(self) -> tuple[dict, dict]:
        road, road_other = self.road_field.value()
        weather, weather_other = self.weather_field.value()
        kss_text = self.kss_label.text()
        fields = {"kss_score": int(kss_text) if kss_text else None, "road_condition": road, "weather": weather}
        overrides = {"road_condition": road_other, "weather": weather_other}
        return fields, overrides

    def load_values(self, fields: dict, overrides: dict):
        self.road_field.set_value(fields.get("road_condition", ""))
        self.weather_field.set_value(fields.get("weather", ""))


# ------------------------------------------------------------------
class CognitiveLabelForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)

        self.task_type_label = QLabel("")
        layout.addRow("태스크", self.task_type_label)

        # survey json에서 파싱된 값 그대로 - 라벨러가 바꿀 필요 없어서 고정 표시만 함
        self.difficulty_label = QLabel("")
        layout.addRow("난이도", self.difficulty_label)

        self.weather_field = ComboWithOther(WEATHER_OPTIONS)
        layout.addRow("날씨", self.weather_field)

    def set_prefill(self, task_type: str, difficulty: str):
        self.task_type_label.setText(task_type)
        self.difficulty_label.setText(difficulty)

    def get_label_fields(self) -> tuple[dict, dict]:
        weather, weather_other = self.weather_field.value()
        fields = {"difficulty": self.difficulty_label.text(), "weather": weather}
        overrides = {"difficulty": False, "weather": weather_other}
        return fields, overrides

    def load_values(self, fields: dict, overrides: dict):
        self.weather_field.set_value(fields.get("weather", ""))
