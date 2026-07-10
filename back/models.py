"""
라벨링 도메인 모델.

핵심 개념
---------
TaskWindow
    survey json에서 파싱되어 타임라인에 "미리" 그려지는 구간.
    라벨러가 만드는 게 아니라 실험 프로토콜 기록에서 자동 생성됨.
    - cognitive: cognitive_task_results[] 1개 -> TaskWindow 1개
      (pre_nback1~3, pre_cbt1~3, post_nback1~3, post_cbt1~3 중 하나로 명명)
    - distraction: driving_task_results[] 1개 -> TaskWindow 1개
      (이 안에 drowsiness 서브구간 prefill이 함께 들어있음)

LabelDraft
    라벨러가 실제로 확정하기 전까지 임시로 들고 있는 작업 중 라벨.
    "하나씩 저장하면 수정 불가능" 정책 때문에, 최종 커밋 전까지는
    DraftStore(로컬 파일)에만 남아있고 실제 segment 폴더로는 export되지 않음.
    최종 커밋될 때 SegmentExporter가 이 draft를 읽어서 실제 파일을 자름.

시나리오별 독립 카운터
    distraction_segment001, drowsiness_segment001, cognitive/pre_nback1...
    은 서로 완전히 독립된 번호 체계 (사용자 확인 완료).
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Scenario(str, Enum):
    DISTRACTION = "distraction"
    DROWSINESS = "drowsiness"
    COGNITIVE = "cognitive"


# ------------------------------------------------------------------
# TaskWindow: survey json 파싱 결과 (타임라인 프리필 마커)
# ------------------------------------------------------------------
@dataclass
class TaskWindow:
    scenario: Scenario
    window_id: str                 # 예: "driving_task_1", "cognitive_pre_nback1" (내부 식별용)
    start_time: datetime           # 절대 시각 (KST, survey json 기준)
    end_time: datetime
    extra: dict = field(default_factory=dict)  # kss_score, task_text, difficulty 등 원본 필드 보존

    @property
    def start_ts(self) -> float:
        return self.start_time.timestamp()

    @property
    def end_ts(self) -> float:
        return self.end_time.timestamp()


@dataclass
class DistractionTaskWindow(TaskWindow):
    """distraction task window는 drowsiness 서브구간을 prefill로 포함."""
    distraction_task_id: str = ""
    distraction_task_text: str = ""
    kss_score: Optional[int] = None
    kss_label: str = ""

    @property
    def drowsiness_window(self) -> tuple[datetime, datetime]:
        """질문 시작(start_time) 이전 1분. 구두 답변 음성이 섞이지 않도록."""
        from datetime import timedelta
        return (self.start_time - timedelta(seconds=60), self.start_time)


@dataclass
class CognitiveTaskWindow(TaskWindow):
    task_name: str = ""    # pre_nback1, pre_cbt3, post_nback2 ...
    task_type: str = ""    # "nback" | "cbt"
    difficulty: str = ""   # "easy" | "normal" | "hard"
    phase: str = ""        # "pre" | "post"


# ------------------------------------------------------------------
# LabelDraft: 라벨러가 실제로 자른 구간 (최종 커밋 전까지 임시 보관)
# ------------------------------------------------------------------
@dataclass
class LabelDraft:
    draft_id: str                  # uuid, draft 식별용
    scenario: Scenario
    start_ts: float                # 절대 unix time (초, float)
    end_ts: float
    source_window_id: Optional[str] = None   # 어느 TaskWindow에서 파생됐는지 (없을 수도 있음)
    label_fields: dict = field(default_factory=dict)
    # distraction 예: {"area": "...", "verb": "...", "noun": "...",
    #                  "verb_detail": "...", "noun_detail": "...",
    #                  "road_condition": "...", "weather": "..."}
    # drowsiness 예: {"kss_score": 5, "road_condition": "...", "weather": "..."}
    # cognitive 예: {"difficulty": "hard", "weather": "..."}
    is_free_text_override: dict = field(default_factory=dict)
    # 필드별로 "기타" 선택 시 자유 서술을 썼는지 표시: {"area": True, ...}
    committed: bool = False        # 최종 export 완료 여부
