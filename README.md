# DMS Labeling Tool

DMS(운전자 모니터링 시스템) 멀티센서 주행 녹화 데이터에 `distraction`(주의분산),
`drowsiness`(졸음), `cognitive`(인지) 세 시나리오로 라벨을 붙이는 PySide6 데스크톱
앱. 확정된 라벨 구간은 절대시간(unix time) 기준으로 모든 센서 파일에서 동시에
프레임/샘플 단위로 잘라 `session_XXX_id_XXX/{scenario}/{segment}/...` 구조로
저장한다.

이 문서는 새로 이 프로젝트를 맡는 개발자가 처음 읽는 진입점이다. 각 항목별
자세한 내용은 아래 "문서 지도"에서 연결되는 문서를 따라가면 된다.

## 문서 지도

이 저장소의 문서는 목적별로 나뉘어 있다.

| 문서 | 용도 |
|---|---|
| `README.md` (이 파일) | 프로젝트 개요, 실행 방법, 확정된 규칙, 아직 안 정해진 것 |
| `CLAUDE.md` | Claude Code(AI 코딩 에이전트)용 프로젝트 요약. 아키텍처/명령어를 간결하게 정리했고, 사람이 읽어도 같은 내용이 유용하다 |
| `docs/*.md` (파일별 상세 문서, 22개) | `back/`, `front/` 각 소스 파일 하나당 문서 하나. 그 파일을 "가져다 쓰는 곳" 표, 핵심 메서드 동작 원리, `technical_reference.md` 관련 절 번호 링크 포함. 코드를 고치기 전에 해당 파일 문서부터 읽는 것을 권장 |
| `docs/module_map.html` (`.png`는 같은 내용의 스크린샷) | 22개 파일 간 의존 관계를 topological depth 기준 6단계로 그린 다이어그램 + 추천 읽는 순서. 브라우저로 열면 됨 |
| `technical_reference.md` | 구현/설계/버그 히스토리 통합 문서. "어떻게 구현되어 있고, 왜 이렇게 설계했고, 어떤 버그를 찾아서 어떻게 고쳤나"를 주제 24개로 통합 서술(2부) + 22개 파일 각각의 구현 상세를 모은 참조(3부). 대화 인용 포함 |
| `DEPLOY.md` | 개발자가 비개발자 라벨러에게 실행 파일로 배포하는 방법 (리눅스/윈도우 빌드) |
| `설치_안내.md` | 라벨러(비개발자) 본인이 보는 설치/실행 안내. 개발 관련 내용 없음 |

새 기능을 추가하거나 버그를 고치는 작업 순서로는 다음을 권장한다:
1. `docs/module_map.html`에서 건드릴 파일이 어디 위치하는지, 무엇을 가져다 쓰는지 확인
2. 그 파일의 `docs/xxx.md`를 읽고, 링크된 `technical_reference.md` 절을 따라가서 배경(구현 이유, 관련 버그 이력) 파악
3. 코드 수정
4. 관련 `docs/xxx.md`와 (설계가 바뀌었거나 버그를 고쳤다면) `technical_reference.md`를 갱신 — 이 저장소는 코드를 바꾸면 관련 문서도 같이 갱신하는 것을 관례로 한다

## 폴더 구조

```
labeling_tool/
  back/     # 데이터 레이어: 파싱 / 정렬 / 컷 / 저장 (Qt 의존성 없음, 단독 실행/테스트 가능)
  front/    # PySide6 UI: back의 클래스들을 가져다 화면과 상호작용에 연결
  docs/     # 파일별 상세 문서 + 의존 관계 다이어그램
  docker/   # 리눅스 크로스버전 빌드용 Dockerfile
  .github/workflows/   # 윈도우 빌드 GitHub Actions
  assets/   # 아이콘, 리눅스 데스크톱 등록 스크립트
```

`back`은 PySide6 없이도(순수 파이썬 + opencv-python/soundfile/openpyxl/numpy만으로)
동작한다 — UI 없이 배치 처리 스크립트로 쓰거나 다른 프론트엔드로 교체하기 쉽다.
`back`은 `front`를 import하지 않는다(단방향 의존).

## 환경/실행

개발/실행 모두 우분투 기준(윈도우 배포는 GitHub Actions 크로스빌드로 별도 지원,
아래 `DEPLOY.md` 참고).

```bash
sudo apt install ffmpeg          # OpenCV VideoWriter(mp4v)가 시스템 ffmpeg 필요
pip install -r requirements.txt

# UI 실행
cd front && python main.py /path/to/DMS_Actions.xlsx   # xlsx 인자 생략 시 "기타" 자유서술로만 라벨링 가능

# 대안 진입점 (PyInstaller가 빌드에 쓰는 것과 동일, sys.path 처리 추가됨)
python run_app.py [/path/to/DMS_Actions.xlsx]

# 진단: 원본 트라이얼의 프레임/샘플 수를 아무것도 바꾸지 않고 점검
python check_av_frames.py <home_dir> <trial_folder_name>
```

자동화된 테스트/린트/CI 설정은 없다. 검증은 실측 데이터를 가진 실제 trial
폴더에 대해 `back/`의 함수를 직접 호출해 결과를 확인하는 스크립트 기반 검증과,
디스플레이/오디오 장치가 없는 환경을 위한 headless 검증(아래 참고)으로 해왔다.

## back 모듈

| 파일 | 역할 | 상세 문서 |
|---|---|---|
| `back/__init__.py` | 패키지 마커 | - |
| `back/models.py` | `TaskWindow`(자동 마커) / `LabelDraft`(라벨러가 만든 임시 구간) 데이터클래스 | `docs/back_models.md` |
| `back/session_loader.py` | 원본 trial 폴더 스캔, 카메라/오디오/imu/radar/watch/survey 파일을 스트림별로 그룹핑한 `TrialData` 생성 | `docs/back_session_loader.md` |
| `back/survey_parser.py` | survey json → `TaskWindow` 리스트 (`intro`, `cognitive_before/after_driving`, `driving`) | `docs/back_survey_parser.md` |
| `back/timestamp_index.py` | 절대시각 ↔ 프레임/샘플 인덱스 변환 (카메라: 프레임, 오디오: 청크→샘플), 세그먼트별 timestamp csv 스티칭 | `docs/back_timestamp_index.md` |
| `back/audio_stitcher.py` | 재생용으로 오디오 세그먼트들을 하나의 연속 wav처럼 이어붙임 | `docs/back_audio_stitcher.md` |
| `back/radar_index.py` | `radar_raw/segNNN/` 스캔, `ros_time_sec` 기준 프레임 절대시각 인덱스 | `docs/back_radar_index.md` |
| `back/coverage.py` | 센서별 대략적인 커버리지(세그먼트별 시작~끝 시각)를 가볍게 조회. 프레임 정확도가 아니라 "이 구간에 데이터가 있는지" 빠른 판단용 (라벨링 화면의 "데이터 없음" 경고 배너) | `docs/back_coverage.md` |
| `back/draft_store.py` | 최종 커밋 전까지 timestamp+label만 로컬 보관 (자유롭게 수정 가능한 작업 상태) | `docs/back_draft_store.md` |
| `back/segment_exporter.py` | 확정된 draft → 프레임 정확도 비디오 컷 + 오디오/센서 csv 슬라이싱 → 최종 저장. 센서별 실제 녹화 공백이 있으면 요청 구간 길이에 맞춰 패딩(오디오: 무음, 비디오: 경계 프레임 반복) | `docs/back_segment_exporter.md` |
| `back/label_taxonomy.py` | `DMS_Actions.xlsx` → Area→{verbs, nouns} 구조 (+ "기타" 자유서술 지원) | `docs/back_label_taxonomy.md` |
| `back/video_codec.py` | OS별로 실제 동작하는 mp4 fourcc 자동 탐지 | `docs/back_video_codec.md` |

## front 모듈

```bash
cd front && python main.py /path/to/DMS_Actions.xlsx
```

| 파일 | 역할 | 상세 문서 |
|---|---|---|
| `front/main.py`, `run_app.py` | 진입점 | `docs/entry_points.md` |
| `front/main_window.py` | StartPage → 시나리오 선택 → LabelingPage 흐름, 세션별 DraftStore/SegmentExporter 생성 | `docs/front_main_window.md` |
| `front/start_page.py` | home 디렉토리(`bags/` 상위) 선택, 트라이얼 선택 | `docs/front_start_page.md` |
| `front/labeling_page_loader.py` | LabelingPage 생성 전 무거운 계산(카메라 인덱스, 오디오 스티칭)을 백그라운드 스레드에서 먼저 끝내는 로더 — 화면 전환 시 "응답 없음" 방지 | `docs/front_labeling_page_loader.md` |
| `front/labeling_page.py` | 시나리오 공통 라벨링 페이지 (타임라인+6분할 비디오+라벨폼+draft 관리) | `docs/front_labeling_page.md` |
| `front/export_worker.py` | 최종 저장(export)을 백그라운드 스레드에서 실행 — 구간당 수초~수십초 걸리는 재인코딩 동안 UI가 멈추지 않게 함 | `docs/front_export_worker.md` |
| `front/stream_player.py` | 절대시각 → 특정 카메라 스트림 프레임 (순차 재생은 빠르게, 탐색은 seek) | `docs/front_stream_player.md` |
| `front/playback_controller.py` | 대시보드 마이크 오디오를 마스터 클럭으로 6개 영상 동기화 (오디오 없으면 QTimer 폴백) | `docs/front_playback_controller.md` |
| `front/widgets/timeline_widget.py` | task window 마커 + draft 구간 + playhead, 클릭으로 seek | `docs/front_widgets_timeline_widget.md` |
| `front/widgets/video_panel.py` | 프레임 표시 QLabel. "스트림 자체 없음"과 "지금 이 시각엔 프레임 없음"을 구분 표시 | `docs/front_widgets_video_panel.md` |
| `front/widgets/label_forms.py` | 시나리오별 라벨 폼 (Area→Verb/Noun 계층 + "기타" 자유서술 공통 패턴) | `docs/front_widgets_label_forms.md` |

`DISPLAY_STREAMS`(`front/labeling_page.py`)가 라벨링 화면에 실제로 그릴 카메라
패널을 결정한다 — 현재 depth 스트림은 표시되지 않는다.

## 확정된 도메인 규칙

1. **절대시간 기준 정렬/컷**: 모든 센서를 공통 unix time(`t_sec`)으로 정렬 후, 라벨 구간의 절대 시작~끝으로 전 센서를 동시에 자름
2. **카메라/오디오 세그먼트 스티칭**: 같은 스트림의 여러 세그먼트 파일(seg001, seg003, seg006...)은 파일별 timestamp csv 기준으로 하나의 가상 연속 타임라인처럼 취급. 세그먼트 번호는 연속하지 않을 수 있음(녹화 재시작 시 새 seg 추가) — 오직 정렬 순서만 신뢰
3. **비디오 컷은 프레임 단위 정확도** (재인코딩 방식, `ffmpeg -ss` 키프레임 탐색 방식 사용 안 함)
4. **drowsiness 구간**: `driving_task.start_time`(질문 시작 시각) **이전** 1분 고정, 라벨러가 조정 불가 (구두 답변 음성이 안 섞이도록)
5. **distraction 구간**: 하나의 task window 안에서 지시문이 복합 동작이면(예: "열었다가 닫아주세요") 라벨러가 필요한 만큼 서브구간으로 나눠 각각 라벨링 가능. 서브구간 개수 제한 없음
6. **구간 잠금 여부**: `drowsiness`/`cognitive`는 survey json에서 계산된 구간을 그대로 쓰고 라벨러가 재조정 불가(`TaskWindow`/`LabelDraft.boundaries_locked`). `distraction`만 자유롭게 여러 서브구간으로 자를 수 있음
7. **segment 번호 체계**: `distraction_segmentNNN` / `drowsiness_segmentNNN`는 시나리오별로 완전히 독립된 카운터. `cognitive`는 카운터 없이 `pre_nback1~3, pre_cbt1~3, post_nback1~3, post_cbt1~3` 고정 이름 사용
8. **라벨 입력 UX**: 카테고리형 필드(영역/동사/명사/도로상황/날씨 등)는 목록 선택 + "기타" 선택 시 자유 서술 입력 (`LabelDraft.is_free_text_override`로 필드별 표시)
9. **저장 정책**: 작업 중엔 `DraftStore`에 timestamp+label만 임시 저장(자유롭게 수정 가능), "최종 저장" 시점에만 `SegmentExporter`가 실제 파일을 잘라 커밋 (커밋 후 되돌리기 없음, 비가역으로 취급)
10. **export 시 센서 간 길이 패딩**: 라벨 구간이 어떤 센서의 실제 녹화 공백과 일부만 겹치면(완전히 안 겹치는 게 아니라), 그 센서 출력을 요청 구간 길이(`end_ts - start_ts`)에 맞춰 채운다 — 오디오는 무음(0 PCM), 비디오는 재생 중 공백 처리와 동일한 원칙(공백의 시간상 중간 지점을 기준으로 더 가까운 쪽 경계 프레임을 반복)으로 채운다. 겹치는 실제 데이터가 하나도 없는 센서는 여전히 파일 자체를 만들지 않음 (`technical_reference.md` 2부 17번)

## 아직 확정 안 된 것 (TODO)

1. **watch 폴더 실제 파일/컬럼명**: `watch_hr.csv` 등의 정확한 컬럼명(예: `timestamp` vs `t_sec`)을 실측 샘플로 확인 못함 — 현재 `_filter_csv_by_time`이 `timestamp`/`t_sec` 둘 다 시도하도록 방어적으로 짜뒀지만, 실제 컬럼명이 다르면 조용히 빈 파일이 나올 수 있음
2. **distraction_task_id → Area/Verb/Noun 매핑**: `"1_2"` 같은 id가 xlsx의 verb/noun 순서와 정확히 일치하지 않아서, 자동 프리필이 아니라 라벨러가 `distraction_task_text` 힌트를 보고 직접 선택하는 방식으로 남겨둠 (매핑표가 따로 있으면 자동 프리필 가능)
3. **레이더 seg 폴더 간 시간 역전 가능성**: `RadarTimestampIndex`는 안전하게 `ros_time_sec` 기준으로 전체 재정렬하지만, 서로 다른 seg의 프레임이 실제로 뒤섞여 저장되는 경우가 있다면(정상적으론 없어야 함) 프레임 하나하나가 별도 파일 I/O를 일으켜 느려질 수 있음 — 필요시 연속 구간 배치 read로 최적화 가능

## 검증 방법

디스플레이/오디오 장치가 없는 환경(개발 컨테이너)에서는 다음 방식을 조합해 검증한다:
- `QT_QPA_PLATFORM=offscreen`으로 `QApplication`/각 페이지가 예외 없이 생성되는지 확인
- `widget.grab()`으로 실제 렌더링된 화면을 PNG로 저장해 레이아웃 확인
- PulseAudio 더미 싱크(`module-null-sink`)로 `QMediaPlayer`를 실제 이벤트 루프에서 재생시켜 `positionChanged`가 진행되는지 확인
- `back/`의 함수를 실제 trial 데이터(실측 timestamp csv, 실제 mp4/wav)에 직접 호출해 프레임 수/바이트/시각 값을 계산값과 비교. 손실 재인코딩 때문에 완전 바이트 동일 비교가 안 되는 mp4의 경우 평균 픽셀 절대 차이(mean abs diff)로 "같은 내용의 압축 잡음"과 "실제로 다른 내용"을 구분 (전자는 관측상 2~7 범위, 후자는 26~30 범위)

세부 검증 시나리오와 실제로 잡아낸 버그들은 `technical_reference.md` 2부에
주제별로 정리돼 있다.

## 빌드/배포

라벨러(비개발자)에게 실행 파일로 배포하는 방법은 `DEPLOY.md` 참고 (리눅스
크로스버전 빌드, 윈도우 GitHub Actions 빌드, 데스크톱 아이콘 등록). 라벨러
본인이 보는 설치 안내는 `설치_안내.md`.
