# 배포 가이드 (비개발자 라벨러용 단일 실행 파일)

라벨러가 파이썬을 몰라도 실행 파일 하나를 더블클릭하면 되도록 배포하는 방법입니다.

## 개념

- **빌드는 개발자가 한 번** (파이썬/PyInstaller 있는 우분투 머신에서)
- **라벨러는 실행 파일만 받아서 더블클릭** (파이썬 설치 불필요)
- 단, 실행 파일이 시스템 라이브러리 몇 개(ffmpeg, libxcb-cursor 등)에는 의존하므로
  라벨러 PC에 그것만 한 번 깔아주면 됩니다 (아래 참고).

## A. 빌드 (개발자, 1회)

**중요: 배포 대상과 같은 우분투 버전/아키텍처 머신에서 빌드하세요.**
PyInstaller는 빌드한 OS에 맞는 바이너리만 만듭니다. (예: Ubuntu 22.04 x86_64에
배포할 거면 Ubuntu 22.04 x86_64에서 빌드)

```bash
cd labeling_tool
cp /경로/DMS_Actions.xlsx ./DMS_Actions.xlsx   # 있으면 번들에 자동 포함
chmod +x build.sh
./build.sh
```

빌드가 끝나면 `dist/dms_labeling` 실행 파일(약 180MB)이 생깁니다.

이 컨테이너(Ubuntu 24, Python 3.12, PySide6 6.11)에서 실제로 빌드 → 실행 파일
정상 기동까지 검증 완료했습니다.

## B. 라벨러 PC 준비 (1회)

실행 파일은 단독으로 대부분 돌아가지만, 아래 시스템 라이브러리에 의존합니다.
라벨러 PC(우분투)에서 한 번만 설치해주세요:

```bash
sudo apt update
sudo apt install -y ffmpeg libxcb-cursor0 libtiff5
# libtiff5가 없다는 최신 우분투(24.04+)라면: sudo apt install -y libtiff6
```

- **ffmpeg**: OpenCV로 mp4 자르기/읽기에 필요 (이게 없으면 영상 컷/재생 실패)
- **libxcb-cursor0**: Qt GUI가 X11 환경에서 뜨기 위해 필요 (빌드 시 경고로 확인됨)
- **libtiff5/6**: Qt 이미지 플러그인 의존성

## C. 배포 & 실행 (라벨러)

개발자가 라벨러에게 전달할 것:
1. `dms_labeling` 실행 파일
2. `DMS_Actions.xlsx` (실행 파일과 **같은 폴더**에 두면 자동 인식됨)

라벨러 실행:
```bash
chmod +x dms_labeling      # 최초 1회 실행 권한 부여
./dms_labeling             # 또는 파일 관리자에서 더블클릭
```

xlsx를 실행 파일 옆에 안 두면, 실행 시 인자로 경로를 줄 수도 있습니다:
```bash
./dms_labeling /경로/DMS_Actions.xlsx
```

## 문제 해결

- **"cannot execute" / 창이 안 뜸**: `libxcb-cursor0` 설치 확인. 그래도 안 되면
  터미널에서 실행해 에러 메시지를 보세요. (spec 파일의 `console=False`를 `True`로
  바꿔 다시 빌드하면 에러 로그가 콘솔에 뜹니다.)
- **영상은 나오는데 소리 안 남 / 재생 안 움직임**: `ffmpeg`, `pulseaudio` 설치 확인.
- **실행 파일이 너무 큼(180MB)**: PySide6+OpenCV 특성상 정상입니다. 더 줄이려면
  spec의 `excludes`에 안 쓰는 모듈을 추가하거나, `--onedir`(폴더 배포) 방식으로
  바꾸면 시작이 조금 빨라집니다.
- **다른 우분투 버전에서 안 됨**: 그 버전에서 다시 빌드해야 합니다. 여러 버전을
  지원하려면 각 버전에서 각각 빌드하거나, AppImage/Flatpak 같은 배포 포맷을
  고려하세요.

## 대안: AppImage (선택)

여러 우분투 버전에 하나의 파일로 배포하고 싶다면 AppImage가 더 견고합니다.
`linuxdeploy` + `linuxdeploy-plugin-qt`로 만들 수 있는데, 설정이 더 복잡해서
지금은 PyInstaller 단일 파일로 시작하고, 배포 대상 우분투 버전이 여러 개로
늘어나면 그때 AppImage로 전환하는 걸 권장합니다.
