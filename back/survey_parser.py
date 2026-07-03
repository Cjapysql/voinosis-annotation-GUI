"""
survey/*.json 파싱 -> TaskWindow 리스트 생성.

트라이얼 폴더의 survey/ 안에는 section_name이 다른 여러 json이 있음:
  - intro                        : 피험자 기본 정보 (TaskWindow 아님)
  - cognitive_before_driving     : pre_nback1~3, pre_cbt1~3
  - cognitive_after_driving      : post_nback1~3, post_cbt1~3  (아직 실제 샘플 못 받음 - 구조는 before와 동일하다고 가정)
  - driving                      : distraction task window + drowsiness prefill

주의: cognitive_after_driving 실제 파일을 아직 못 봤어서, before와 동일한
스키마(payload.cognitive_task_results)를 가정합니다. 다르면 알려주세요.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Scenario, TaskWindow, DistractionTaskWindow, CognitiveTaskWindow


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class SurveyParser:
    def __init__(self, survey_dir: str):
        self.survey_dir = Path(survey_dir)
        self._sections: dict[str, list[dict]] = {}
        self._load_all()

    def _load_all(self):
        for path in sorted(self.survey_dir.glob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            section = data.get("section_name", "unknown")
            self._sections.setdefault(section, []).append(data)

    def get_intro(self) -> Optional[dict]:
        docs = self._sections.get("intro")
        return docs[0]["payload"] if docs else None

    # ------------------------------------------------------------------
    def parse_cognitive_windows(self) -> list[CognitiveTaskWindow]:
        windows = []
        windows += self._parse_cognitive_section("cognitive_before_driving", phase="pre")
        windows += self._parse_cognitive_section("cognitive_after_driving", phase="post")
        return windows

    def _parse_cognitive_section(self, section_name: str, phase: str) -> list[CognitiveTaskWindow]:
        docs = self._sections.get(section_name, [])
        if not docs:
            return []
        payload = docs[0]["payload"]
        results = payload.get("cognitive_task_results", [])

        # task_type별로 등장 순서대로 1,2,3 번호 부여 (난이도 순서 그대로 사용)
        counters = {"nback": 0, "cbt": 0}
        windows = []
        for item in results:
            task_type = item["task_type"]
            counters[task_type] += 1
            task_name = f"{phase}_{task_type}{counters[task_type]}"
            windows.append(CognitiveTaskWindow(
                scenario=Scenario.COGNITIVE,
                window_id=f"cognitive_{task_name}",
                start_time=_parse_dt(item["start_time"]),
                end_time=_parse_dt(item["end_time"]),
                extra=item,
                task_name=task_name,
                task_type=task_type,
                difficulty=item.get("difficulty", ""),
                phase=phase,
            ))
        return windows

    # ------------------------------------------------------------------
    def parse_distraction_windows(self) -> list[DistractionTaskWindow]:
        docs = self._sections.get("driving", [])
        if not docs:
            return []
        payload = docs[0]["payload"]
        results = payload.get("driving_task_results", [])

        windows = []
        for i, item in enumerate(results, start=1):
            windows.append(DistractionTaskWindow(
                scenario=Scenario.DISTRACTION,
                window_id=f"driving_task_{i}",
                start_time=_parse_dt(item["start_time"]),
                end_time=_parse_dt(item["end_time"]),
                extra=item,
                distraction_task_id=item.get("distraction_task_id", ""),
                distraction_task_text=item.get("distraction_task_text", ""),
                kss_score=item.get("kss_score"),
                kss_label=item.get("kss_label", ""),
            ))
        return windows

    # ------------------------------------------------------------------
    def parse_all(self) -> dict[str, list[TaskWindow]]:
        return {
            "cognitive": self.parse_cognitive_windows(),
            "distraction": self.parse_distraction_windows(),
            # drowsiness는 별도 섹션이 없고 distraction window에 내장되어 있음
            # (DistractionTaskWindow.drowsiness_window 참고)
        }

