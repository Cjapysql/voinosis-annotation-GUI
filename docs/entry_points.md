# 진입점: `front/main.py` / `run_app.py`

앱을 시작하는 두 개의 스크립트. 실질적으로 하는 일은 같다(`MainWindow`를
만들어 띄움) - `run_app.py`는 PyInstaller 빌드와 sys.path 처리가 추가된
버전.

## `front/main.py`

```
python main.py [DMS_Actions.xlsx 경로]
```

`front/` 디렉토리 안에서 직접 실행하는 용도(`CLAUDE.md`의 `cd front && python
main.py` 명령). `sys.argv[1]`을 xlsx 경로로 받아(생략하면 `None`)
`front.main_window.MainWindow(dms_actions_xlsx=xlsx_path)`를 만들고 `show()`.
xlsx를 생략하면 distraction 라벨 폼의 Area/Verb/Noun 드롭다운이 `"기타"`만
있는 상태로 뜬다(자유 서술로만 라벨링 가능, 완전히 막히지는 않음).

## `run_app.py`

프로젝트 루트에서 실행하는 진입점이자, PyInstaller가 빌드할 때 쓰는 스크립트
(`dms_labeling.spec`의 `Analysis(["run_app.py"], ...)`). `front/main.py`와
달리 두 가지가 추가된다:

### `_resource_base()`

`sys.frozen`(PyInstaller로 번들됐는지)이 참이면 `sys._MEIPASS`(번들이 실행 시
압축 해제되는 임시 폴더), 아니면 이 파일이 있는 위치(프로젝트 루트)를
반환한다. `main()`이 이 경로를 `sys.path`에 추가해서(`if str(base) not in
sys.path: sys.path.insert(0, str(base))`) `back`/`front` 패키지를 어느
실행 방식(스크립트 직접 실행, 번들된 실행 파일)에서든 확실히 import할 수
있게 한다.

### `_find_default_xlsx()`

명령줄 인자로 xlsx 경로를 안 넘기면, 아래 세 위치를 순서대로 시도해서 처음
존재하는 걸 쓴다:
1. **번들된 실행 파일과 같은 디렉토리**(`sys.executable`의 부모) - 배포 후
   라벨러가 실행 파일 옆에 xlsx를 직접 둔 경우. `sys.frozen`일 때만 확인.
2. **번들 내부 리소스**(`_resource_base()` 아래) - 빌드 시점에 xlsx가 프로젝트
   루트에 있었으면 `dms_labeling.spec`의 `datas` 로직이 자동으로 번들에 포함
   시킨 경우.
3. **현재 작업 디렉토리**.

이 우선순위 때문에, 배포된 실행 파일 옆에 새 xlsx를 놓으면(번들에 포함된
것보다) 그게 항상 먼저 채택된다 - 빌드 후에 라벨 목록만 따로 갱신하고 싶을
때 재빌드 없이 파일 교체만으로 가능하게 하는 설계.

### `main()`

`_resource_base()`를 `sys.path`에 추가한 뒤(그래야 `from front.main_window
import MainWindow`가 어디서 실행하든 가능), `sys.argv[1]` 또는
`_find_default_xlsx()`로 xlsx 경로를 정하고, `MainWindow(dms_actions_xlsx=
xlsx_path)`를 만들어 `show()`. `front/main.py`와 동일하게 `QApplication`을
만들고 `app.exec()`로 이벤트 루프 진입.
