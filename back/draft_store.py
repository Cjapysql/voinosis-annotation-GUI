"""
라벨 draft 임시 저장소.

정책 (PDF 기반):
  - 작업 중에는 timestamp + label만 로컬 draft 파일에 저장 (수정 가능)
  - "모든 task 구분 후 최종 저장" 시점에만 SegmentExporter가 실제
    센서 파일들을 잘라 최종 segment 폴더 구조로 내보냄 (그 이후엔 수정 불가 취급)

draft 파일은 트라이얼별로 하나 (트라이얼 폴더 바깥, 별도 작업 디렉토리에 저장해서
원본 raw 데이터 폴더를 건드리지 않음).
"""
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .models import LabelDraft, Scenario


class DraftStore:
    def __init__(self, draft_path: str):
        self.draft_path = Path(draft_path)
        self.drafts: dict[str, LabelDraft] = {}
        if self.draft_path.exists():
            self._load()

    def _load(self):
        with open(self.draft_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for d in raw.get("drafts", []):
            d["scenario"] = Scenario(d["scenario"])
            self.drafts[d["draft_id"]] = LabelDraft(**d)

    def save(self):
        self.draft_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "drafts": [
                {**asdict(d), "scenario": d.scenario.value}
                for d in self.drafts.values()
            ]
        }
        with open(self.draft_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    def add_draft(self, scenario: Scenario, start_ts: float, end_ts: float,
                  source_window_id: str = None, label_fields: dict = None) -> LabelDraft:
        draft = LabelDraft(
            draft_id=uuid.uuid4().hex[:8],
            scenario=scenario,
            start_ts=start_ts,
            end_ts=end_ts,
            source_window_id=source_window_id,
            label_fields=label_fields or {},
        )
        self.drafts[draft.draft_id] = draft
        self.save()
        return draft

    def update_draft(self, draft_id: str, **kwargs):
        draft = self.drafts[draft_id]
        for k, v in kwargs.items():
            setattr(draft, k, v)
        self.save()

    def remove_draft(self, draft_id: str):
        self.drafts.pop(draft_id, None)
        self.save()

    def drafts_for_scenario(self, scenario: Scenario) -> list[LabelDraft]:
        return sorted(
            (d for d in self.drafts.values() if d.scenario == scenario and not d.committed),
            key=lambda d: d.start_ts,
        )

    def committed_window_ids(self, scenario: Scenario) -> set:
        """이미 최종 저장된 draft가 있는 source_window_id 집합 (진행 상황 표시용)."""
        return {
            d.source_window_id for d in self.drafts.values()
            if d.scenario == scenario and d.committed and d.source_window_id
        }

    def find_overlap(self, scenario: Scenario, start_ts: float, end_ts: float,
                      exclude_draft_id: str = None) -> LabelDraft | None:
        """같은 시나리오의 확정 전 draft들 중 [start_ts, end_ts]와 시간이 겹치는 걸 찾음."""
        for d in self.drafts.values():
            if d.scenario != scenario or d.committed:
                continue
            if exclude_draft_id and d.draft_id == exclude_draft_id:
                continue
            if start_ts < d.end_ts and d.start_ts < end_ts:
                return d
        return None

    def mark_committed(self, draft_id: str):
        self.drafts[draft_id].committed = True
        self.save()
