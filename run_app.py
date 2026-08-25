"""
DMS 라벨링 툴 최상위 진입점 (PyInstaller 빌드 및 일반 실행 공통).

실행 방법:
    python run_app.py [DMS_Actions.xlsx 경로]

DMS_Actions.xlsx 경로를 생략하면, 실행 파일과 같은 폴더(또는 PyInstaller로
번들된 내부 리소스)에서 DMS_Actions.xlsx를 자동으로 찾습니다.

에러 로그: 시작 중 예외가 나거나(임포트 실패, 창 생성 실패 등) 실행 중
잡히지 않은 예외가 발생하면, 실행 파일과 같은 폴더에 dms_labeling_error.log
파일로 스택트레이스를 남긴다. PyInstaller로 빌드된 실행 파일은
console=False(콘솔 창 숨김)라서 - 윈도우에서는 특히 stdout/stderr 자체가
아예 사라져 터미널에서 실행해도 에러 메시지가 안 보인다 - 콘솔 유무와
무관하게 항상 진단 가능하도록 파일로 남기는 것.
"""
import sys
import os
import traceback
import datetime
from pathlib import Path


def _resource_base() -> Path:
    """PyInstaller로 번들되면 sys._MEIPASS(임시 추출 폴더), 아니면 이 파일 위치."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _find_default_xlsx() -> str | None:
    """실행 파일 옆 또는 번들 내부에서 DMS_Actions.xlsx 자동 탐색."""
    candidates = []
    # 1) 실행 파일과 같은 디렉토리 (배포 후 라벨러가 옆에 둔 경우)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "DMS_Actions.xlsx")
    # 2) 번들 내부 리소스 (빌드 시 포함시킨 경우)
    candidates.append(_resource_base() / "DMS_Actions.xlsx")
    # 3) 현재 작업 디렉토리
    candidates.append(Path.cwd() / "DMS_Actions.xlsx")

    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _log_path() -> Path:
    """에러 로그를 남길 위치 - 실행 파일(또는 이 스크립트)과 같은 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "dms_labeling_error.log"
    return Path(__file__).resolve().parent / "dms_labeling_error.log"


def _log_crash(exc_type, exc_value, exc_tb) -> None:
    """예외를 파일에 이어쓴다(여러 번 실행/여러 크래시가 하나의 파일에 시간순으로
    쌓임 - 콘솔이 없어도 항상 확인 가능하도록)."""
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n===== {timestamp} =====\n{text}")
    except Exception:
        pass  # 로그 남기다가 또 에러 나면 그냥 포기(원래 에러를 덮지 않기 위함)


def main():
    # Qt 이벤트 루프 안(슬롯/콜백)에서 잡히지 않은 예외도 파일로 남긴다.
    sys.excepthook = _log_crash

    try:
        # back / front 패키지를 확실히 import할 수 있도록 이 파일 위치를 경로에 추가
        base = _resource_base()
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))

        from PySide6.QtWidgets import QApplication
        from front.main_window import MainWindow

        xlsx_path = sys.argv[1] if len(sys.argv) > 1 else _find_default_xlsx()

        app = QApplication(sys.argv)
        app.setApplicationName("DMS Labeling Tool")

        window = MainWindow(dms_actions_xlsx=xlsx_path)
        window.show()

        sys.exit(app.exec())
    except SystemExit:
        raise
    except Exception:
        _log_crash(*sys.exc_info())
        sys.exit(1)


if __name__ == "__main__":
    main()
