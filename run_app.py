"""
DMS 라벨링 툴 최상위 진입점 (PyInstaller 빌드 및 일반 실행 공통).

실행 방법:
    python run_app.py [DMS_Actions.xlsx 경로]

DMS_Actions.xlsx 경로를 생략하면, 실행 파일과 같은 폴더(또는 PyInstaller로
번들된 내부 리소스)에서 DMS_Actions.xlsx를 자동으로 찾습니다.
"""
import sys
import os
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


def main():
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


if __name__ == "__main__":
    main()
