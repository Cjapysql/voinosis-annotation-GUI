# voinosis-annotation-GUI
# DMS Labeling Tool - 데이터/파싱/익스포트 레이어

이미 수집된 원본 데이터(`<home>/bags/<trial>/...`)를 읽어 라벨링하고,
확정된 라벨 구간을 절대시간 기준으로 모든 센서에서 잘라
`session_XXX_id_XXX/{scenario}/{segment}/...` 구조로 저장하는 백엔드 모듈.

**이번 스캐폴딩 범위**: 데이터 레이어(파싱/정렬/컷/저장)만. UI는 별도로 다시 설계 예정.

## 환경

수집/실행 모두 우분투 기준. but 크로스os가능

```bash
sudo apt install ffmpeg    # OpenCV VideoWriter(mp4v)가 시스템 ffmpeg 필요
pip install -r requirements.txt
```

이 컨테이너(Ubuntu 24, OpenCV 4.13 + FFMPEG 빌드)에서 mp4v 인코딩 정상 동작 확인함.

## 모듈

| 파일 | 역할 |
|---|---|
| `models.py` | `TaskWindow`(자동 마커) / `LabelDraft`(라벨러가 만든 임시 구간) 데이터클래스 |
| `survey_parser.py` | survey json → `TaskWindow` 리스트 (cognitive_before/after, driving) |
| `label_taxonomy.py` | `DMS_Actions.xlsx` → Area→{verbs, nouns} 구조 (+ "기타" 자유서술 지원) |
| `session_loader.py` | 원본 trial 폴더 스캔 (카메라 seg 파일 스티칭, 오디오/imu/radar/watch/survey 경로 매핑) |
| `timestamp_index.py` | 절대시각 ↔ 프레임/샘플 인덱스 변환 (카메라: 프레임, 오디오: 청크→샘플) |
| `draft_store.py` | 최종 커밋 전까지 timestamp+label만 로컬 보관 (수정 가능한 작업 상태) |
| `segment_exporter.py` | 확정된 draft → 프레임 정확도 비디오 컷 + 오디오/센서 csv 슬라이싱 → 최종 저장 |

## 실제 검증된 것 (실제 데이터 + 목업 데이터로 테스트 완료)

- `survey_parser`: 3개 json(intro, cognitive_before_driving, driving)으로 실제 파싱 확인
  - drowsiness 구간이 `start_time - 60s ~ start_time`으로 정확히 계산됨
- `label_taxonomy`: `DMS_Actions.xlsx` 실제 파싱 → 6개 Area, Area별 verb/noun 목록 정상 추출
- `session_loader`: `front_color_seg001/003/006.mp4` 같은 파일명 → `driver/rgb`로 정규화, seg 번호 기준 정렬
- `timestamp_index` + `segment_exporter`: 2개 seg 파일에 걸친 프레임 구간을 프레임 단위로 정확히 잘라 이어붙이는 것 확인, 오디오 청크 기준 샘플 인덱스 계산 확인, imu/watch csv 시간 필터링 확인
- `video_codec`: OS별 실제 동작하는 fourcc 자동 탐지 (이 환경에서는 mp4v 확인됨)
- `radar_index` + `segment_exporter._export_radar`: 실제 레이더 raw bin(132프레임)에서 특정 구간(frame 5~10)을 byte 단위로 잘라, 원본과 **바이트 완전 일치**하는 것 검증. cfg/sha256 보존도 확인

## 확정된 규칙 (대화에서 합의된 것)

1. **절대시간 기준 정렬/컷**: 모든 센서를 공통 unix time(`t_sec`)으로 정렬 후, 라벨 구간의 절대 시작~끝으로 전 센서를 동시에 자름
2. **카메라 seg 파일 스티칭**: 같은 스트림의 여러 mp4(seg001, seg003, seg006...)는 timestamp csv의 연속된 frame_idx 기준으로 하나의 가상 연속 타임라인처럼 취급
3. **비디오 컷은 프레임 단위 정확도** (재인코딩 방식, ffmpeg -ss 키프레임 탐색 방식 사용 안 함)
4. **drowsiness 구간**: `driving_task_results[i].start_time`(질문 시작 시각) **이전** 1분 고정 (구두 답변 음성이 안 섞이도록)
5. **distraction 구간**: 하나의 task window 안에서 지시문이 복합 동작이면(예: "열었다가 닫아주세요") 라벨러가 필요한 만큼(2개, 3개...) 서브구간으로 나눠 각각 라벨링
6. **segment 번호 체계**: `distraction_segmentNNN` / `drowsiness_segmentNNN`는 서로 완전히 독립된 카운터. `cognitive`는 카운터 없이 `pre_nback1~3, pre_cbt1~3, post_nback1~3, post_cbt1~3` 고정 이름 사용
7. **라벨 입력 UX**: 카테고리형 필드(영역/동사/명사/도로상황/날씨 등)는 목록 선택 + "기타" 선택 시 자유 서술 입력 (`LabelDraft.is_free_text_override`로 필드별 표시)
8. **저장 정책**: 작업 중엔 `DraftStore`에 timestamp+label만 임시 저장(수정 가능), 모든 task 라벨링 완료 후 "최종 저장" 시점에 `SegmentExporter`가 실제 파일을 잘라 커밋 (커밋 후 수정 불가 취급)

## 아직 확정 안 된 것 (TODO)

1. **`cognitive_after_driving`**: 실제 샘플 json을 못 받아서 `cognitive_before_driving`과 동일 스키마라고 가정하고 구현. 다르면 `survey_parser._parse_cognitive_section` 수정 필요
2. **watch 폴더 실제 파일/컬럼명**: `watch_hr.csv` 등의 정확한 컬럼명(예: `timestamp` vs `t_sec`)을 실측 샘플로 확인 못함 — 현재 `_filter_csv_by_time`이 `timestamp`/`t_sec` 둘 다 시도하도록 방어적으로 짜뒀지만, 실제 컬럼명이 다르면 조용히 빈 파일이 나올 수 있음 (경고 로그 추가 권장)
3. **distraction_task_id → Area/Verb/Noun 매핑**: `"1_2"` 같은 id가 xlsx의 verb/noun 순서와 정확히 일치하지 않아서, 자동 프리필이 아니라 라벨러가 `distraction_task_text` 힌트를 보고 직접 선택하는 방식으로 남겨둠 (매핑표가 따로 있으면 자동 프리필 가능)
4. **복합 동작 분할 개수 제한**: 현재 제한 없음(라벨러 자유). 제한이 필요하면 `LabelDraft` 생성 시점에 검증 로직 추가
5. **레이더 seg 폴더 간 시간 역전 가능성**: `RadarTimestampIndex`는 안전하게 `ros_time_sec` 기준으로 전체 재정렬하지만, 만약 서로 다른 seg의 프레임이 실제로 뒤섞여 저장되는 경우가 있다면(정상적으론 없어야 함) 프레임 하나하나가 별도 파일 I/O를 일으켜 느려질 수 있음 — 필요시 연속 구간 배치 read로 최적화 가능

## 다음 단계 제안

- PySide6 라벨링 UI (타임라인 + 6분할 비디오 + Area/Verb/Noun 계층 드롭다운) 설계 — PDF 시나리오 기반으로 다시 잡기로 하셨으니 별도 진행
