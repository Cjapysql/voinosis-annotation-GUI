"""
DMS 라벨링 툴 실행 진입점.

사용법:
    python main.py [DMS_Actions.xlsx 경로]

xlsx 경로를 생략하면 distraction 라벨 폼의 Area/Verb/Noun 드롭다운이
"기타"만 있는 상태로 뜹니다 (자유 서술로만 라벨링 가능).
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main_window import MainWindow


def main():
    xlsx_path = sys.argv[1] if len(sys.argv) > 1 else None

    app = QApplication(sys.argv)
    app.setApplicationName("DMS Labeling Tool")

    window = MainWindow(dms_actions_xlsx=xlsx_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
