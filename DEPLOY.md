# 배포 가이드 (비개발자 라벨러용 단일 실행 파일)

라벨러가 파이썬을 몰라도 실행 파일 하나를 더블클릭하면 되도록 배포하는 방법.
리눅스(우분투)와 윈도우 두 플랫폼을 지원한다.

## 개념

- **빌드는 개발자가 한다** (라벨러 PC에는 파이썬 설치 불필요)
- PyInstaller는 크로스 컴파일이 안 된다 — 빌드한 OS/아키텍처용 바이너리만
  만든다. 리눅스용은 리눅스에서, 윈도우용은 윈도우에서 빌드해야 함
- 실행 파일은 시스템 라이브러리 일부(ffmpeg 등)에는 여전히 의존하므로,
  라벨러 PC에 그것만 한 번 깔아주면 됨

## A. 리눅스 빌드

리눅스 빌드는 두 가지 방법이 있다. **여러 우분투 버전에 배포할 계획이면
`build_linux_2204.sh`(Docker) 방식을 쓴다.**

### A-1. `build_linux_2204.sh` (권장 — Docker, 우분투 22.04 기준 고정)

```bash
cd labeling_tool
chmod +x build_linux_2204.sh
./build_linux_2204.sh
```

PyInstaller가 만드는 바이너리는 "빌드한 머신의 glibc 버전 이상"인 곳에서만
실행된다(glibc는 하위 호환 — 새 버전에서 만들면 옛날 버전에서 못 돌아가지만
그 반대는 됨). 이 스크립트는 지금 이 머신의 우분투 버전과 무관하게, Docker로
우분투 22.04(`docker/Dockerfile.build`, 라벨러들이 쓰는 가장 오래된 버전)
컨테이너를 띄워 그 안에서 빌드한다 — 결과물은 22.04 이상 어디서나(24.04
포함) 동작한다. Docker만 설치돼 있으면 되고, 빌드 머신 자체의 우분투
버전은 상관없다.

결과물: `dist/dms_labeling`.

### A-2. `build.sh` (Docker 없이, 지금 이 머신 버전으로만 빌드)

```bash
cd labeling_tool
cp /경로/DMS_Actions.xlsx ./DMS_Actions.xlsx   # 있으면 번들과 같은 폴더에 자동 포함
chmod +x build.sh
./build.sh          # python3 -m venv .venv && pip install -r requirements.txt pyinstaller && pyinstaller dms_labeling.spec
```

**배포 대상과 반드시 같은 우분투 버전/아키텍처 머신에서 빌드해야 한다.**
다른 버전에 배포할 거면 A-1을 쓰거나, 그 버전에서 따로 빌드해야 함.

### 리눅스 배포 패키지 구성

개발자가 라벨러에게 전달할 것:
1. `dist/dms_labeling` 실행 파일
2. `DMS_Actions.xlsx` (실행 파일과 **같은 폴더**에 두면 자동 인식)
3. `assets/` 폴더(`icon.png`, `install_linux.sh`) — 데스크톱 아이콘 등록용

위 세 가지를 `dms_labeling_dist/` 같은 폴더 하나에 모은 뒤 **zip으로
압축**해서 전달한다(`dms_labeling_ubuntu2204.zip` 같은 이름 - 리눅스/
윈도우 라벨러 모두 압축 유틸이 기본 내장돼 있어 별도 설치 없이 풀 수
있음). `설치_안내.md`가 라벨러에게 배포하는 이 zip 파일의 압축 해제 →
실행까지의 단계를 이미 담고 있으므로, 이 파일도 같은 폴더에 함께
포함해서 압축하면 된다.

## B. 윈도우 빌드 (`.github/workflows/build-windows.yml`)

윈도우 PC가 없어도 GitHub Actions가 호스팅하는 윈도우 러너를 빌려서 빌드한다.

- GitHub 저장소의 Actions 탭에서 "Windows 빌드" 워크플로우를 수동 실행
  (`workflow_dispatch`), 또는 `v1.0.0` 같은 `v*` 태그를 push하면 자동 실행됨
- 완료되면 Actions 실행 결과의 Artifacts에서 `dms_labeling-windows.zip`
  (내용물: `dist/dms_labeling.exe`, `DMS_Actions.xlsx`)을 내려받음
- 윈도우 라벨러 PC에는 ffmpeg 설치가 별도로 필요 (아래 C 참고, 설치 방법만
  윈도우용으로 다름 — `winget install ffmpeg` 또는 공식 배포본 압축 해제 후
  PATH 등록)

## C. 라벨러 PC 준비 (공통, 리눅스 기준)

실행 파일은 단독으로 대부분 돌아가지만, 아래 시스템 라이브러리에 의존한다.
라벨러 PC(우분투)에서 한 번만 설치하면 됨:

```bash
sudo apt update
sudo apt install -y ffmpeg libxcb-cursor0 libtiff5
# libtiff5가 없다는 최신 우분투(24.04+)라면: sudo apt install -y libtiff6
```

- **ffmpeg**: OpenCV로 mp4 자르기/읽기에 필요 (이게 없으면 영상 컷/재생 실패)
- **libxcb-cursor0**: Qt GUI가 X11 환경에서 뜨기 위해 필요
- **libtiff5/6**: Qt 이미지 플러그인 의존성

`docker/Dockerfile.build`로 빌드한 실행 파일은 Qt의 xcb 플랫폼 플러그인이
쓰는 추가 라이브러리들(`libxcb-icccm4` 등)을 빌드 시점에 이미 번들에
포함시키므로, 라벨러 PC에서 별도로 더 설치할 필요는 없다 — 위 세 개만
있으면 됨.

## D. 데스크톱 아이콘 등록 (`assets/install_linux.sh`, 선택이지만 권장)

리눅스 실행 파일(ELF)은 윈도우/macOS와 달리 파일 안에 아이콘을 내장하는
표준 방식이 없다. `.desktop` 파일(리눅스 데스크톱 표준 규격)로 등록해야
앱 목록/작업표시줄에 아이콘과 함께 뜬다.

```bash
cd dist/   # 또는 배포받은 압축을 푼 폴더 (dms_labeling 실행 파일이 있는 위치의 상위)
./assets/install_linux.sh
```

sudo 권한 없이 현재 사용자 계정(`~/.local/share/dms_labeling`,
`~/.local/share/applications`)에만 설치된다. `dist/dms_labeling`(개발
프로젝트 안)과 `dms_labeling`(배포 압축 최상위) 두 경로 모두 자동으로
찾는다.

## 문제 해결

- **"cannot execute" / 창이 안 뜸**: `libxcb-cursor0` 설치 확인. 그래도 안 되면
  터미널에서 실행해 에러 메시지를 보기 (`dms_labeling.spec`의 `console=False`를
  `True`로 바꿔 다시 빌드하면 에러 로그가 콘솔에 뜸)
- **영상은 나오는데 소리 안 남 / 재생 안 움직임**: `ffmpeg`, `pulseaudio` 설치 확인
- **실행 파일이 너무 큼(약 180MB)**: PySide6+OpenCV 특성상 정상. 더 줄이려면
  `dms_labeling.spec`의 `excludes`에 안 쓰는 모듈을 추가하거나, `--onedir`(폴더
  배포) 방식으로 바꾸면 시작이 조금 빨라짐
- **다른 우분투 버전에서 안 됨**: A-2(`build.sh`)로 빌드했다면 A-1
  (`build_linux_2204.sh`)로 다시 빌드. A-1로 빌드했는데도 22.04보다 오래된
  버전에서 안 되는 경우는 지원 범위 밖(22.04 미만은 미지원)
- **윈도우에서 "Windows Defender가 실행을 막았습니다"**: PyInstaller로 만든
  미서명 실행 파일은 흔히 발생. "추가 정보" → "실행" 클릭 (코드 서명 인증서를
  구매해 서명하면 근본적으로 해결되지만 현재 미적용)

## 대안: AppImage/Flatpak (미적용, 참고용)

여러 우분투 버전에 하나의 파일로 배포하는 또 다른 방법으로 AppImage/Flatpak도
있으나, 현재는 `build_linux_2204.sh`(Docker + 최저 버전 기준 glibc 빌드)로
이미 다중 버전 지원을 해결했으므로 별도로 도입하지 않았다.
