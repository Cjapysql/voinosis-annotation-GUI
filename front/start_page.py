"""
시작 페이지: home 디렉토리(그 안에 bags/ 가 있는 경로) 입력 -> 트라이얼(세션) 폴더 선택 -> 시작.
"""
import sys
from pathlib import Path

from back.session_loader import SessionLoader

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QFileDialog, QDialog
)


class StartPage(QWidget):
    session_selected = Signal(str, str)  # (home_dir, trial_folder_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>DMS 라벨링 툴</h2>"))
        layout.addWidget(QLabel("home 디렉토리 (하위에 bags/ 폴더가 있는 경로)"))

        row = QHBoxLayout()
        self.home_dir_input = QLineEdit()
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self.home_dir_input)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        refresh_btn = QPushButton("트라이얼 목록 불러오기")
        refresh_btn.clicked.connect(self._refresh_trials)
        layout.addWidget(refresh_btn)

        layout.addWidget(QLabel("데이터 세션(트라이얼) 선택"))
        self.trial_combo = QComboBox()
        layout.addWidget(self.trial_combo)

        start_btn = QPushButton("시작")
        start_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        start_btn.clicked.connect(self._on_start)
        layout.addWidget(start_btn)

        layout.addStretch()

    def _show_warning(self, title, message):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(500)
        dlg_layout = QVBoxLayout(dialog)

        label = QLabel(message)
        label.setWordWrap(True)
        dlg_layout.addWidget(label)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dialog.accept)
        dlg_layout.addWidget(ok_btn)

        dialog.exec()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "home 디렉토리 선택")
        if path:
            self.home_dir_input.setText(path)
            self._refresh_trials()

    def _refresh_trials(self):
        home_dir = self.home_dir_input.text().strip()
        if not home_dir:
            return
        loader = SessionLoader(home_dir)
        trials = loader.list_trials()
        self.trial_combo.clear()
        self.trial_combo.addItems(trials)
        if not trials:
            bags_dir = str(Path(home_dir) / "bags")
            self._show_warning("없음", f"{bags_dir}\n안에 트라이얼 폴더가 없습니다.")

    def _on_start(self):
        home_dir = self.home_dir_input.text().strip()
        trial = self.trial_combo.currentText()
        if not home_dir or not trial:
            self._show_warning("입력 필요", "home 디렉토리와 트라이얼을 선택해주세요.")
            return
        self.session_selected.emit(home_dir, trial)
