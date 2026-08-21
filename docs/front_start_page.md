# `front/start_page.py`

앱을 열면 가장 먼저 보이는 화면. home 디렉토리(하위에 `bags/`가 있는 경로)를
입력/선택하고, 그 안의 트라이얼(세션) 폴더 목록에서 하나를 골라 "시작"을
누르면 다음 단계로 넘어간다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `StartPage` | `QStackedWidget`의 첫 페이지로 추가, `session_selected` 시그널을 받아 세션 로드 진행 |

## 이 파일이 가져다 쓰는 것

`back.session_loader.SessionLoader` - `list_trials()`로 트라이얼 목록 조회.

## 시그널

`session_selected(str, str)`: `(home_dir, trial_folder_name)`. "시작" 버튼을
누르면 emit된다.

## UI 구성

home 디렉토리 입력창 + 찾아보기 버튼, "트라이얼 목록 불러오기" 버튼, 트라이얼
선택 콤보박스, "시작" 버튼.

## `_browse()` - 비블로킹 파일 다이얼로그

`QFileDialog.getExistingDirectory()`(정적 블로킹 호출) 대신 `QFileDialog`
인스턴스를 직접 만들어 `.open()`(비블로킹)으로 띄운다. 블로킹 정적 호출은
다이얼로그가 열려있는 동안 파이썬 실행이 그 함수 안에 멈춰 있어서, 메인 창을
닫아도 앱 전체 종료가 안 될 수 있는 문제가 있었다. `DontUseNativeDialog`
옵션은 OS 고유 네이티브 다이얼로그의 창 관리 이상 동작(뒤로 밀려도 다시
못 가져오는 등)을 피하기 위함. 시작 경로는 `/home/`, 다이얼로그 인스턴스는
`self._browse_dialog`에 보관해 GC로 창이 조기에 닫히지 않게 한다.
`fileSelected` 시그널을 `_on_home_dir_chosen`에 연결해서, 사용자가 실제로
디렉토리를 고르면 그 경로로 입력창을 채우고 바로 `_refresh_trials()`를
호출한다.

## `_refresh_trials()`

입력된 home 디렉토리로 `SessionLoader.list_trials()`를 호출해 트라이얼
콤보박스를 채운다. 목록이 비어있으면(폴더가 없거나 그 안에 트라이얼이 없음)
`_show_warning()`으로 `<home_dir>/bags` 경로를 보여주며 안내.

## `_show_warning(title, message)`

간단한 `QDialog` 기반 안내창(OK 버튼 하나). `QMessageBox` 대신 직접
`QDialog`를 만든 이유는 소스에 명시돼 있지 않음.

## `_on_start()`

home 디렉토리와 트라이얼이 둘 다 선택돼 있는지 확인 후 `session_selected`
emit. `front/main_window.py`의 `_on_session_selected()`가 이 시그널을 받아
실제 트라이얼 로드(`SessionLoader.load_trial`), survey 파싱, `DraftStore`/
`SegmentExporter` 생성을 진행한다.
