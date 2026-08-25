#!/usr/bin/env bash
#
# DMS 라벨링 툴을 리눅스 데스크톱(GNOME/KDE 등)의 앱 목록/작업표시줄에
# 아이콘과 함께 등록한다. 리눅스 실행 파일(ELF)은 윈도우/macOS와 달리
# 파일 안에 아이콘을 내장하는 표준 방식이 없어서, .desktop 파일(리눅스
# 데스크톱 표준 규격)로 "이 실행 파일은 이 아이콘을 쓴다"고 따로 등록해야
# 한다. sudo 권한 없이 현재 사용자 계정에만 설치된다.
#
# 사용법 (dist/dms_labeling 빌드가 끝난 뒤, 딱 한 번만):
#     ./assets/install_linux.sh
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ICON_SRC="$SCRIPT_DIR/icon.png"

# 개발 프로젝트 안에서 쓸 때는 dist/dms_labeling(PyInstaller 출력 경로),
# 라벨러에게 배포하는 압축 파일 안에서 쓸 때는 dms_labeling(최상위) - 둘 다 지원
if [ -f "$PROJECT_DIR/dist/dms_labeling" ]; then
    EXE_SRC="$PROJECT_DIR/dist/dms_labeling"
elif [ -f "$PROJECT_DIR/dms_labeling" ]; then
    EXE_SRC="$PROJECT_DIR/dms_labeling"
else
    echo "dms_labeling 실행 파일을 찾을 수 없습니다."
    echo "  - 개발 중이면 먼저 빌드해주세요 (./build_linux_2204.sh)."
    echo "  - 배포받은 압축 파일이면, 이 스크립트가 압축을 푼 폴더 안(assets/install_linux.sh)에 있는지 확인해주세요."
    exit 1
fi

INSTALL_DIR="$HOME/.local/share/dms_labeling"
mkdir -p "$INSTALL_DIR"
cp "$EXE_SRC" "$INSTALL_DIR/dms_labeling"
cp "$ICON_SRC" "$INSTALL_DIR/icon.png"
chmod +x "$INSTALL_DIR/dms_labeling"

# 실행 파일 옆에 두면 자동으로 찾는 라벨 정의 파일도 있으면 같이 옮겨준다
if [ -f "$PROJECT_DIR/DMS_Actions.xlsx" ]; then
    cp "$PROJECT_DIR/DMS_Actions.xlsx" "$INSTALL_DIR/DMS_Actions.xlsx"
fi

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/dms_labeling.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DMS 라벨링 툴
Comment=DMS(운전자 모니터링) 멀티센서 라벨링 도구
Exec=$INSTALL_DIR/dms_labeling
Icon=$INSTALL_DIR/icon.png
Terminal=false
Categories=Utility;
EOF

echo "설치 완료!"
echo "  실행 파일: $INSTALL_DIR/dms_labeling"
echo "  앱 목록/작업표시줄에서 'DMS 라벨링 툴'을 검색하면 아이콘과 함께 나타납니다."
