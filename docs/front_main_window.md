# `front/main_window.py`

최상위 조립점: `StartPage` -> 시나리오 선택 화면 -> `LabelingPage`(시나리오별)를
`QStackedWidget`으로 전환하며 앱 전체 흐름을 관장한다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main.py`, `run_app.py` | `MainWindow` | 앱 진입점에서 `MainWindow(dms_actions_xlsx=...)`를 만들고 `show()` |

## 이 파일이 가져다 쓰는 것

`back.models.Scenario`, `back.session_loader.SessionLoader`,
`back.survey_parser.SurveyParser`, `back.draft_store.DraftStore`,
`back.segment_exporter.SegmentExporter`, `back.label_taxonomy.load_dms_actions`,
`front.start_page.StartPage`, `front.labeling_page.LabelingPage`,
`front.labeling_page_loader.LabelingPageDataLoader`.

## 출력/draft 경로 규칙

- export 결과: `<home_dir>/labeled_output/session_{trial_num:03d}_id_{subject_id}/`
- draft 임시 파일: `<home_dir>/.labeling_drafts/{trial_folder_name}.json`

원본 raw 데이터 폴더는 절대 건드리지 않는다 - 둘 다 `home_dir` 아래의 별도
디렉토리.

`_TRIAL_NAME_RE = r"^id(?P<id>\w+?)_trial(?P<trial>\d+)_"`로 트라이얼 폴더명에서
`subject_id`/`trial_num`을 뽑아 위 경로 조합에 쓴다.

## `__init__(dms_actions_xlsx=None)`

xlsx 경로가 있으면 `load_dms_actions()`로 `self.areas`를 미리 로드(없으면 빈
리스트 - distraction 폼의 Area/Verb/Noun 드롭다운이 `"기타"`만 남는 상태로
동작). `QStackedWidget`에 `StartPage`(index 0)와 시나리오 선택 페이지(index 1,
`_build_scenario_page()`)를 추가. `_labeling_pages: dict[Scenario, LabelingPage]`로
시나리오별 페이지를 캐시(한 번 만들면 재사용).

## `closeEvent(event)`

`QApplication.instance().quit()`을 호출 - 메인 창을 닫으면 다른 창(예:
`StartPage`의 디렉토리 선택 다이얼로그)이 열려있어도 앱 전체를 종료한다.

## `_on_session_selected(home_dir, trial_folder_name)`

`StartPage.session_selected` 시그널 핸들러. `SessionLoader.load_trial()` ->
`SurveyParser.parse_all()`로 시나리오별 task window 딕셔너리를 만든다
(`drowsiness`는 `distraction` 결과를 그대로 재사용 - `docs/back_survey_parser.md`
참고). 트라이얼 이름을 정규식으로 파싱해 출력 경로/draft 경로를 조합하고,
`DraftStore`와 `SegmentExporter`를 세션당 하나씩 만든다(`SegmentExporter`는
이후 "최종 저장"마다 이 인스턴스를 그대로 안 쓰고 매번 새로 만듦 - `docs/
back_segment_exporter.md` "동시성" 참고, 이 `self._exporter`는 그 새
인스턴스를 만들 때 `session_dir`을 얻는 용도로만 계속 쓰임). 세션이 바뀌면
`_labeling_pages` 캐시를 비운다.

## `_open_labeling(scenario)` / `_finish_open_labeling(...)` - 2단계 페이지 생성

이미 만들어둔 페이지가 있으면 바로 전환. 없으면:
1. 시나리오 버튼 전부 잠금(중복 클릭 방지).
2. `LabelingPageDataLoader`를 만들어 시작(무거운 계산을 백그라운드로).
   `self._pending_loader`에 보관해서 실행 중 GC되지 않게 함.
3. `loaded` 시그널이 오면 `_finish_open_labeling()` - 버튼 재활성화, 미리
   계산된 4개 값(camera_indices, default_mic_name, audio_result,
   sensor_coverage)을 그대로 `LabelingPage` 생성자에 전달, 캐시에 저장,
   `_show_page_when_audio_ready()` 호출.
4. `failed` 시그널이 오면 `_on_labeling_page_load_failed()` - 버튼 재활성화 +
   에러 다이얼로그.

## `_show_page_when_audio_ready(page)`

`page.playback.is_audio_ready`가 이미 참이면 바로 화면 전환. 아니면 시나리오
버튼을 잠그고 `page.playback.audio_ready` 시그널을 기다렸다가(콜백 안에서
`disconnect`로 자기 자신을 해제) 전환한다. 오디오(스티칭된 wav, 수백 MB일 수
있음) 로딩이 실제로 끝나기 전에 화면을 넘기면 `QMediaPlayer.setPosition()`이
조용히 무시돼서 재생을 누르는 순간 의도한 위치가 아니라 맨 처음부터
재생되는 문제가 있었다. 기다리는 동안 버튼을 잠그는 것은 중복 클릭으로
같은 페이지가 여러 번 만들어지는 것도 같이 막는다. (화면에 "로딩 중" 문구를
따로 띄우지는 않는다 - 버튼 잠금만으로 처리하기로 결정된 부분.)

## `_on_back_from_labeling(page)`

`LabelingPage.back_requested` 시그널 핸들러. `page.playback.pause()`를 먼저
호출한 뒤 시나리오 선택 화면(index 1)으로 전환한다. 페이지를 캐시해서 재사용하는
구조라, 재생을 멈추지 않고 화면만 전환하면 화면 밖에서 영상/오디오가 계속
재생되는 문제가 있었다.
