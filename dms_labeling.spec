# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec - DMS 라벨링 툴 단일 실행 파일 빌드.

빌드 (실제 배포 대상과 같은 우분투 머신에서):
    pip install pyinstaller
    pyinstaller dms_labeling.spec

결과물:
    dist/dms_labeling            # 단일 실행 파일 (--onefile)
    또는 dist/dms_labeling/      # 폴더 형태 (--onedir, 아래 COLLECT 사용 시)

주의:
- PyInstaller는 빌드한 OS/아키텍처용 바이너리만 생성합니다. 배포 대상이
  Ubuntu 22.04 x86_64면 그 환경에서 빌드해야 합니다.
- ffmpeg는 시스템 실행 파일이라 번들에 포함되지 않습니다. 배포 머신에
  `apt install ffmpeg`가 되어 있거나, ffmpeg 바이너리를 별도로 동봉해야
  OpenCV VideoWriter가 동작합니다 (README 참고).
"""
import os

block_cipher = None

# DMS_Actions.xlsx를 실행 파일과 함께 두는 대신 번들 내부에 포함시키고 싶으면
# 아래 datas에 경로를 넣으세요. (없으면 빈 리스트로 두고, 라벨러가 실행 파일 옆에
# xlsx를 두면 run_app.py가 자동으로 찾습니다.)
datas = []
_xlsx = os.path.join(os.getcwd(), "DMS_Actions.xlsx")
if os.path.exists(_xlsx):
    datas.append((_xlsx, "."))

a = Analysis(
    ["run_app.py"],
    pathex=[os.getcwd()],   # back, front 패키지를 찾을 수 있도록 루트 추가
    binaries=[],
    datas=datas,
    hiddenimports=[
        # PySide6 멀티미디어/위젯은 동적 로드라 명시 필요할 수 있음
        "PySide6.QtMultimedia",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        # back/front 하위 모듈 (동적 참조 대비 명시)
        "back.models", "back.survey_parser", "back.session_loader",
        "back.timestamp_index", "back.draft_store", "back.segment_exporter",
        "back.label_taxonomy", "back.radar_index", "back.video_codec",
        "front.main_window", "front.start_page", "front.labeling_page",
        "front.stream_player", "front.playback_controller",
        "front.widgets.timeline_widget", "front.widgets.video_panel",
        "front.widgets.label_forms",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 용량 절감: 안 쓰는 무거운 Qt 모듈 제외
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "matplotlib", "tkinter", "PyQt5", "PyQt6",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="dms_labeling",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # GUI 앱이라 콘솔창 숨김. 디버깅 중엔 True로 바꾸면 에러 로그가 보임
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
