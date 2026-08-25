# 배포 가이드 (비개발자 라벨러용 단일 실행 파일)

실행 파일 하나 배포하는 방법.
리눅스(우분투)와 윈도우 두 플랫폼을 지원한다.

- **빌드는 개발자가 한다** (라벨러 PC에는 파이썬 설치 불필요)
- PyInstaller는 크로스 컴파일이 안 된다 — 빌드한 OS/아키텍처용 바이너리만
  만든다. 리눅스용은 리눅스에서, 윈도우용은 윈도우에서 빌드해야 함
- 실행 파일은 시스템 라이브러리 일부(ffmpeg 등)에는 여전히 의존하므로,
  라벨러 PC에 그것만 한 번 깔아주면 됨

## A. 리눅스 빌드 (build_linux_2204.sh, Docker)

프로젝트 루트(labeling_tool/)에서:

```bash
chmod +x build_linux_2204.sh
./build_linux_2204.sh
```

PyInstaller가 만드는 바이너리는 빌드한 머신의 glibc 버전 이상인 곳에서만
실행된다(glibc는 하위 호환 — 새 버전에서 만들면 옛날 버전에서 못 돌아가지만
그 반대는 됨). 이 스크립트는 지금 이 머신의 우분투 버전과 무관하게, Docker로
우분투 22.04(docker/Dockerfile.build, 라벨러들이 쓰는 가장 오래된 버전)
컨테이너를 띄워 그 안에서 빌드한다 — 결과물은 22.04 이상 어디서나(24.04
포함) 동작한다. Docker만 설치돼 있으면 되고, 빌드 머신 자체의 우분투
버전은 상관없다.

빌드가 끝나면 스크립트가 배포용 압축까지 한 번에 만든다:
- dist/dms_labeling — 실행 파일 단독(개발/디버깅용).
- dms_labeling_ubuntu2204.tar.gz — 실행 파일 + (있으면) DMS_Actions.xlsx
  + assets/(아이콘, install_linux.sh)를 한 폴더로 묶어 tar.gz로 압축한
  것. **라벨러에게는 이 파일 하나만 전달하면 된다** — 설치_안내.md가
  이 파일의 압축 해제 → 실행까지의 단계를 안내한다.

zip이 아니라 tar를 쓰는 이유: tar는 유닉스 실행 권한(실행 비트)을
표준적으로 보존해서, 압축을 풀면 dms_labeling이 곧바로 실행 가능한
상태로 나온다(zip은 어떤 도구로 압축했는지에 따라 실행 비트가 유지되지
않을 수 있음). tar는 리눅스에 항상 기본 설치돼 있어 받는 쪽이 별도로
뭘 설치할 필요도 없다.

## B. 윈도우 빌드 (.github/workflows/build-windows.yml)

윈도우 PC가 없어도 GitHub Actions가 호스팅하는 윈도우 러너를 빌려서 빌드한다.

- GitHub 저장소의 Actions 탭에서 Windows 빌드 워크플로우를 수동 실행
  (workflow_dispatch), 또는 v1.0.0 같은 v* 태그를 push하면 자동 실행됨
- 완료되면 Actions 실행 결과의 Artifacts에서 dms_labeling-windows.zip을
  내려받음. 워크플로우가 빌드 직후 DMS_Actions.xlsx를 dist/(실행 파일이
  있는 폴더) 안으로 미리 복사해두므로, 이 zip을 그냥 풀면 dms_labeling.exe와
  DMS_Actions.xlsx가 **이미 같은 폴더**에 들어있다 - 별도 재포장 없이
  그대로 라벨러에게 전달하면 됨(윈도우는 데스크톱 아이콘 등록 스크립트가
  없으므로 이 두 파일이 전부).
- 윈도우 라벨러 PC에는 ffmpeg 설치가 별도로 필요 (아래 C 부분 참고, 설치
  방법만 윈도우용으로 다름 — winget install ffmpeg 또는 공식 배포본 압축
  해제 후 PATH 등록)

## C. 라벨러 PC 준비 (공통, 리눅스 기준)

실행 파일은 단독으로 대부분 돌아가지만, 아래 시스템 라이브러리에 의존한다.

- **ffmpeg**: OpenCV로 mp4 자르기/읽기에 필요(이게 없으면 영상 컷/재생 실패).
  아래 D 부분의 install_linux.sh가 없으면 자동으로 설치해주므로, 그
  스크립트를 실행할 계획이면 따로 준비할 필요 없음.
- **libxcb-cursor0**: Qt GUI가 X11 환경에서 뜨기 위해 필요.
- **libtiff5/6**: Qt 이미지 플러그인 의존성(libtiff5가 없는 최신 우분투
  24.04+는 libtiff6).

docker/Dockerfile.build로 빌드한 실행 파일은 Qt의 xcb 플랫폼 플러그인이
쓰는 추가 라이브러리들(libxcb-icccm4, libxcb-cursor0 등)을 빌드
시점에 이미 번들에 포함시키므로, 실측상 라벨러 PC에 이 라이브러리들이
따로 없어도 정상 동작했다(2026-08-25 헤드리스 실행 검증). 그래도 만약을
대비해 안 될 경우엔 수동 설치:

```bash
sudo apt update
sudo apt install -y ffmpeg libxcb-cursor0 libtiff5
```

## D. 데스크톱 아이콘 등록 (assets/install_linux.sh, 선택이지만 권장)

리눅스 실행 파일(ELF)은 윈도우/macOS와 달리 파일 안에 아이콘을 내장하는
표준 방식이 없다. .desktop 파일(리눅스 데스크톱 표준 규격)로 등록해야
앱 목록/작업표시줄에 아이콘과 함께 뜬다. 이 스크립트는 등록과 함께
ffmpeg가 없으면 자동으로 설치도 해준다(sudo apt-get install -y ffmpeg,
비밀번호를 한 번 물어볼 수 있음) - 위 C 부분의 준비 단계를 이 한 스크립트로
대체할 수 있다.

```bash
cd dist/   # 또는 배포받은 압축을 푼 폴더 (dms_labeling 실행 파일이 있는 위치의 상위)
./assets/install_linux.sh
```

아이콘 등록 자체는 sudo 권한 없이 현재 사용자 계정(~/.local/share/dms_labeling,
~/.local/share/applications)에만 설치된다(ffmpeg가 이미 있으면 sudo
비밀번호 요청 자체가 없음). dist/dms_labeling(개발 프로젝트 안)과
dms_labeling(배포 압축 최상위) 두 경로 모두 자동으로 찾는다.
