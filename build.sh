#!/usr/bin/env bash
#
# DMS 라벨링 툴 단일 실행 파일 빌드 스크립트.
#
# 반드시 "배포 대상과 같은 종류의 우분투 머신"에서 실행하세요.
# (PyInstaller는 빌드한 OS/아키텍처용 바이너리만 생성합니다.)
#
# 사용법:
#     chmod +x build.sh
#     ./build.sh
#
set -e

echo "==> 1/4 시스템 의존성 확인 (ffmpeg)"
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "  ffmpeg가 없습니다. 설치를 시도합니다 (sudo 필요)..."
    sudo apt update && sudo apt install -y ffmpeg
fi

echo "==> 2/4 파이썬 가상환경 준비"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "==> 3/4 의존성 + PyInstaller 설치"
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo "==> 4/4 실행 파일 빌드"
rm -rf build dist
pyinstaller dms_labeling.spec

echo ""
echo "빌드 완료!"
echo "  실행 파일: $(pwd)/dist/dms_labeling"
echo ""
echo "배포 시 함께 챙길 것:"
echo "  - dist/dms_labeling  (실행 파일)"
echo "  - DMS_Actions.xlsx   (실행 파일과 같은 폴더에 두면 자동 인식)"
echo "  - 배포 PC에 ffmpeg 설치 필요 (apt install ffmpeg)"
