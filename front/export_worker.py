"""
드래프트 최종 저장(export)을 백그라운드 스레드에서 돌리기 위한 워커.

SegmentExporter.export_draft()는 카메라 프레임 재인코딩 때문에 구간 하나당 수 초
~수십 초씩 걸릴 수 있다(back/segment_exporter.py 참고). 이걸 메인(UI) 스레드에서
그대로 부르면 그동안 Qt 이벤트 루프가 멈춰서 OS가 "응답 없음"을 띄운다. QThread로
분리해서 export가 도는 동안에도 UI는 계속 반응하게 하고, 진행상황/완료/실패는
시그널로 메인 스레드에 전달한다.

DraftStore.mark_committed()는 일부러 여기서 안 부르고, 메인 스레드가 finished_ok/
failed 시그널을 받은 뒤에 몰아서 호출한다 - draft_store 파일 I/O를 이 백그라운드
스레드와 메인 스레드가 동시에 건드리지 않게 하기 위함.
"""
from PySide6.QtCore import QThread, Signal

from back.models import LabelDraft, TaskWindow
from back.segment_exporter import SegmentExporter


class ExportWorker(QThread):
    progress = Signal(int, int)          # (완료된 개수, 전체 개수)
    step_progress = Signal(str)          # draft 하나 안에서 지금 어느 스트림/단계를 내보내는 중인지
    finished_ok = Signal(list, list)     # ([(draft_id, segment_dir_str), ...], export_warnings)
    failed = Signal(list, str)           # (실패 전까지의 [(draft_id, segment_dir_str), ...], 에러 메시지)

    def __init__(self, exporter: SegmentExporter,
                 jobs: list[tuple[LabelDraft, str | None, TaskWindow | None]], parent=None):
        """jobs: [(draft, cognitive_task_name, source_window), ...]"""
        super().__init__(parent)
        self.exporter = exporter
        self.jobs = jobs

    def run(self):
        committed = []  # [(draft_id, segment_dir_str), ...]
        self.exporter.export_warnings = []
        try:
            for i, (draft, cognitive_task_name, window) in enumerate(self.jobs):
                segment_dir = self.exporter.export_draft(
                    draft, cognitive_task_name=cognitive_task_name, source_window=window,
                    on_progress=self.step_progress.emit,
                )
                committed.append((draft.draft_id, str(segment_dir)))
                self.progress.emit(i + 1, len(self.jobs))
        except Exception as e:
            self.failed.emit(committed, str(e))
            return
        self.finished_ok.emit(committed, self.exporter.export_warnings)
