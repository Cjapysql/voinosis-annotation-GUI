# DMS Labeling Tool

이미 수집된 원본 데이터(`<home>/bags/<trial>/...`)를 읽어 라벨링하고,
확정된 라벨 구간을 절대시간 기준으로 모든 센서에서 잘라
`session_XXX_id_XXX/{scenario}/{segment}/...` 구조로 저장합니다.

## 폴더 구조

```
labeling_tool/
  back/     # 데이터 레이어: 파싱 / 정렬 / 컷 / 저장 (Qt 의존성 없음, 단독 테스트 가능)
  front/    # PySide6 UI: back의 클래스들을 가져다 화면과 상호작용에 연결
```

`back`은 PySide6 없이도(순수 파이썬 + opencv/soundfile/openpyxl만으로) 동작하므로,
UI 없이 배치 처리 스크립트로 쓰거나 다른 프론트엔드로 교체하기도 쉽습니다.

## 환경

수집/실행 모두 우분투 기준.

```bash
sudo apt install ffmpeg    # OpenCV VideoWriter(mp4v)가 시스템 ffmpeg 필요
pip install -r requirements.txt

# UI 실행
cd front
python main.py /path/to/DMS_Actions.xlsx
```

이 컨테이너(Ubuntu 24, OpenCV 4.13 + FFMPEG 빌드)에서 mp4v 인코딩 정상 동작 확인함.

## back 모듈

| 파일 | 역할 |
|---|---|
| `back/__init__.py` | 패키지 마커. `front`에서는 `from back.xxx import yyy` 형태로 사용 |
| `back/models.py` | `TaskWindow`(자동 마커) / `LabelDraft`(라벨러가 만든 임시 구간) 데이터클래스 |
| `back/survey_parser.py` | survey json → `TaskWindow` 리스트 (cognitive_before/after, driving) |
| `back/label_taxonomy.py` | `DMS_Actions.xlsx` → Area→{verbs, nouns} 구조 (+ "기타" 자유서술 지원) |
| `back/session_loader.py` | 원본 trial 폴더 스캔 (카메라 seg 파일 스티칭, 오디오/imu/radar/watch/survey 경로 매핑) |
| `back/timestamp_index.py` | 절대시각 ↔ 프레임/샘플 인덱스 변환 (카메라: 프레임, 오디오: 청크→샘플) |
| `back/draft_store.py` | 최종 커밋 전까지 timestamp+label만 로컬 보관 (수정 가능한 작업 상태) |
| `back/segment_exporter.py` | 확정된 draft → 프레임 정확도 비디오 컷 + 오디오/센서 csv 슬라이싱 → 최종 저장 |
| `back/radar_index.py` | `radar_raw/segNNN/` 스캔, offset_int16 기반 프레임 절대시각 인덱스 |
| `back/video_codec.py` | OS별로 실제 동작하는 mp4 fourcc 자동 탐지 |

## 실제 검증된 것 (실제 데이터 + 목업 데이터로 테스트 완료)

- `survey_parser`: 업로드해주신 3개 json(intro, cognitive_before_driving, driving)으로 실제 파싱 확인
  - drowsiness 구간이 `start_time - 60s ~ start_time`으로 정확히 계산됨
- `label_taxonomy`: `DMS_Actions.xlsx` 실제 파싱 → 6개 Area, Area별 verb/noun 목록 정상 추출
- `session_loader`: `front_color_seg001/003/006.mp4` 같은 파일명 → `driver/rgb`로 정규화, seg 번호 기준 정렬
- `timestamp_index` + `segment_exporter`: 2개 seg 파일에 걸친 프레임 구간을 프레임 단위로 정확히 잘라 이어붙이는 것 확인, 오디오 청크 기준 샘플 인덱스 계산 확인, imu/watch csv 시간 필터링 확인
- `video_codec`: OS별 실제 동작하는 fourcc 자동 탐지 (이 환경에서는 mp4v 확인됨)
- `radar_index` + `segment_exporter._export_radar`: 실제 레이더 raw bin(132프레임)에서 특정 구간(frame 5~10)을 byte 단위로 잘라, 원본과 **바이트 완전 일치**하는 것 검증. cfg/sha256 보존도 확인

## 확정된 규칙

1. **절대시간 기준 정렬/컷**: 모든 센서를 공통 unix time(`t_sec`)으로 정렬 후, 라벨 구간의 절대 시작~끝으로 전 센서를 동시에 자름
2. **카메라 seg 파일 스티칭**: 같은 스트림의 여러 mp4(seg001, seg003, seg006...)는 timestamp csv의 연속된 frame_idx 기준으로 하나의 가상 연속 타임라인처럼 취급
3. **비디오 컷은 프레임 단위 정확도** (재인코딩 방식, ffmpeg -ss 키프레임 탐색 방식 사용 안 함)
4. **drowsiness 구간**: `driving_task_results[i].start_time`(질문 시작 시각) **이전** 1분 고정 (구두 답변 음성이 안 섞이도록)
5. **distraction 구간**: 하나의 task window 안에서 지시문이 복합 동작이면(예: "열었다가 닫아주세요") 라벨러가 필요한 만큼(2개, 3개...) 서브구간으로 나눠 각각 라벨링
6. **segment 번호 체계**: `distraction_segmentNNN` / `drowsiness_segmentNNN`는 서로 완전히 독립된 카운터. `cognitive`는 카운터 없이 `pre_nback1~3, pre_cbt1~3, post_nback1~3, post_cbt1~3` 고정 이름 사용
7. **라벨 입력 UX**: 카테고리형 필드(영역/동사/명사/도로상황/날씨 등)는 목록 선택 + "기타" 선택 시 자유 서술 입력 (`LabelDraft.is_free_text_override`로 필드별 표시)
8. **저장 정책**: 작업 중엔 `DraftStore`에 timestamp+label만 임시 저장(수정 가능), 모든 task 라벨링 완료 후 "최종 저장" 시점에 `SegmentExporter`가 실제 파일을 잘라 커밋 (커밋 후 수정 불가 취급)

## 아직 확정 안 된 것

1. **`cognitive_after_driving`**: 실제 샘플 json을 못 받아서 `cognitive_before_driving`과 동일 스키마라고 가정하고 구현. 다르면 `survey_parser._parse_cognitive_section` 수정 필요
2. **watch 폴더 실제 파일/컬럼명**: `watch_hr.csv` 등의 정확한 컬럼명(예: `timestamp` vs `t_sec`)을 실측 샘플로 확인 못함 — 현재 `_filter_csv_by_time`이 `timestamp`/`t_sec` 둘 다 시도하도록 방어적으로 짜뒀지만, 실제 컬럼명이 다르면 조용히 빈 파일이 나올 수 있음 (경고 로그 추가 권장)
3. **distraction_task_id → Area/Verb/Noun 매핑**: `"1_2"` 같은 id가 xlsx의 verb/noun 순서와 정확히 일치하지 않아서, 자동 프리필이 아니라 라벨러가 `distraction_task_text` 힌트를 보고 직접 선택하는 방식으로 남겨둠 (매핑표가 따로 있으면 자동 프리필 가능)
4. **복합 동작 분할 개수 제한**: 현재 제한 없음(라벨러 자유). 제한이 필요하면 `LabelDraft` 생성 시점에 검증 로직 추가
5. **레이더 seg 폴더 간 시간 역전 가능성**: `RadarTimestampIndex`는 안전하게 `ros_time_sec` 기준으로 전체 재정렬하지만, 만약 서로 다른 seg의 프레임이 실제로 뒤섞여 저장되는 경우가 있다면(정상적으론 없어야 함) 프레임 하나하나가 별도 파일 I/O를 일으켜 느려질 수 있음 — 필요시 연속 구간 배치 read로 최적화 가능

## front 모듈 (`front/`)

PDF 시나리오 기반 PySide6 라벨링 앱. `back`의 클래스들을 `from back.xxx import yyy`로 가져다 씀.

```bash
cd front
python main.py /path/to/DMS_Actions.xlsx   # xlsx 생략 시 "기타" 자유서술로만 라벨링 가능
```

| 파일 | 역할 |
|---|---|
| `front/main.py` | 진입점 |
| `front/main_window.py` | StartPage → 시나리오 선택 → LabelingPage 흐름, 세션별 DraftStore/SegmentExporter 생성 |
| `front/start_page.py` | home 디렉토리(bags/ 상위) 선택, 트라이얼 선택 |
| `front/labeling_page.py` | 시나리오 공통 라벨링 페이지 (타임라인+6분할 비디오+라벨폼+draft 관리) |
| `front/stream_player.py` | 절대시각 → 특정 카메라 스트림 프레임 (순차 재생은 빠르게, 탐색은 seek) |
| `front/playback_controller.py` | 대시보드 마이크 오디오를 마스터 클럭으로 6개 영상 동기화 (오디오 없으면 QTimer 폴백) |
| `front/widgets/timeline_widget.py` | task window 마커 + draft 구간 + playhead, 클릭으로 seek |
| `front/widgets/video_panel.py` | 프레임 표시 QLabel |
| `front/widgets/label_forms.py` | 시나리오별 라벨 폼 (Area→Verb/Noun 계층 + "기타" 자유서술 공통 패턴) |

### 설계 결정 (PDF 목업과 다른 부분)

- **구간 시작/끝 지정**: PDF는 타임라인 위 드래그 핸들(●)이지만, 마우스 드래그 픽셀 좌표는 이 환경에서 시각적으로 검증할 수 없어 **"시작점 지정"/"끝점 지정" 버튼으로 현재 playhead 위치를 캡처**하는 방식으로 구현. 기능은 동일(구간 시작/끝 선택), 안정성이 더 높음.
- **구간 잠금 규칙**: `drowsiness`(질문 시작 전 1분 고정)와 `cognitive`(survey json의 실제 start/end, 특히 CBT는 "타임바를 움직이지 않게")는 TaskWindow에서 자동 계산된 구간을 그대로 쓰고 라벨러가 임의로 재조정할 수 없게(`boundaries_locked=True`) 했습니다. `distraction`만 자유롭게 여러 서브구간으로 자를 수 있습니다. 이 잠금 여부가 대화에서 명시적으로 확정되지 않은 부분(특히 cognitive의 nback도 잠글지)이 있어서, 필요하면 `LabelingPage.boundaries_locked` 조건만 바꾸면 됩니다.
- **최종 저장**: "저장" 버튼은 `DraftStore`에만 쌓이고(수정 가능), "최종 저장(모두 커밋)" 버튼을 눌러야 `SegmentExporter`가 실제 파일을 자릅니다 (PDF의 "timestamp, label만 저장해두고 최종 완료되면 한번에 저장" 반영).

### 검증 방법 (헤드리스 컨테이너 환경의 한계)

이 환경은 디스플레이/오디오 장치가 없어서 실제 화면을 보거나 오디오 재생을 눈/귀로 확인할 수 없습니다. 대신:
- `QT_QPA_PLATFORM=offscreen`으로 `QApplication`/모든 페이지가 예외 없이 생성되는 것 확인 (구조적 스모크 테스트)
- playhead를 수동으로 옮겨가며 시작/끝점 지정 → 라벨 폼 입력 → draft 저장 → 최종 커밋까지 실제로 실행해서 `session_XXX_id_XXX/distraction/distraction_segment001/annotation.json`이 정확한 값으로 만들어지는 것 확인
- 실제 오디오 재생(`QMediaPlayer.positionChanged`가 영상 동기화를 구동하는 부분)은 이 컨테이너에 오디오 장치가 없어서(`PulseAudioService 연결 실패`) 못 돌려봤습니다 — **실제 배포 머신에서 재생/일시정지 버튼 눌렀을 때 영상이 오디오랑 같이 움직이는지 꼭 확인해주세요.** 안 움직이면 `playback_controller.py`의 폴백(QTimer) 경로로 바꾸거나 오디오 백엔드(ffmpeg/pulseaudio) 설치를 점검하면 됩니다.

## 다음 단계 제안

- 실제 배포 머신(디스플레이+오디오 있는 우분투)에서 `front/main.py` 실행해서 재생/오디오 동기화 육안 확인
- 레이더 `radar_raw/segNNN`처럼 카메라도 `depth` 스트림이 UI에서 안 보이는데, 필요하면 `DISPLAY_STREAMS`(front/labeling_page.py)에 depth 패널 추가
