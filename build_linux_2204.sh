#!/usr/bin/env bash
#
# 우분투 22.04(라벨러들이 쓰는 가장 오래된 버전) 기준으로 Docker 컨테이너
# 안에서 빌드해서, 그보다 새 우분투(24.04 등)에서도 확실히 돌아가는 실행
# 파일을 만든다. 지금 이 머신의 우분투 버전과 무관하게 항상 22.04 기준
# 결과물이 나온다.
#
# 사용법:
#     chmod +x build_linux_2204.sh
#     ./build_linux_2204.sh
#
set -e

cd "$(dirname "$0")"

IMAGE_TAG="dms-labeling-build-2204"

echo "==> 1/2 우분투 22.04 빌드 환경 이미지 준비"
docker build -t "$IMAGE_TAG" -f docker/Dockerfile.build .

echo "==> 2/3 컨테이너 안에서 빌드 (호스트의 .venv/build/dist와 겹치지 않게 별도 venv 사용)"
docker run --rm -v "$(pwd)":/build -w /build "$IMAGE_TAG" bash -c '
    set -e
    rm -rf build dist .venv_docker
    python3 -m venv .venv_docker
    . .venv_docker/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt pyinstaller
    pyinstaller dms_labeling.spec
'

echo "==> 3/3 배포용 tar.gz 패키징"
# DEPLOY.md의 "리눅스 배포 패키지 구성"과 동일한 내용을 자동으로 묶는다:
# 실행 파일 + (있으면) DMS_Actions.xlsx + assets/(아이콘, 데스크톱 등록 스크립트).
PKG_DIR="dms_labeling_dist"
PKG_TAR="dms_labeling_ubuntu2204.tar.gz"
rm -rf "$PKG_DIR" "$PKG_TAR"
mkdir "$PKG_DIR"
cp dist/dms_labeling "$PKG_DIR"/
[ -f DMS_Actions.xlsx ] && cp DMS_Actions.xlsx "$PKG_DIR"/
cp -r assets "$PKG_DIR"/
tar czf "$PKG_TAR" "$PKG_DIR"
rm -rf "$PKG_DIR"

echo ""
echo "빌드 완료! (우분투 22.04 기준 - 22.04 이상 어디서나 실행 가능)"
echo "  실행 파일: $(pwd)/dist/dms_labeling"
echo "  배포용 압축: $(pwd)/$PKG_TAR"
echo ""
echo "라벨러 PC에는 ffmpeg 설치가 별도로 필요합니다 (apt install ffmpeg)."
