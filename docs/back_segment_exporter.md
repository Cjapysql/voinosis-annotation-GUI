# `back/segment_exporter.py`

확정된 `LabelDraft`를 받아서 모든 센서 데이터를 절대시각(`start_ts`~`end_ts`) 기준으로
프레임/샘플 정확도로 잘라 `session_XXX_id_XXX/{scenario}/{segment_name}/` 구조로
저장하고, `annotation.json` + `annotations/{scenario}.csv`를 남긴다. 이 파일이
Draft/Export 분리 원칙에서 "Export"에 해당하는 유일한 진입점이다 - 이 모듈이
호출되기 전까지는 어떤 센서 파일도 실제로 잘리지 않는다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `front/main_window.py` | `SegmentExporter` | 세션 선택 시 `self._exporter` 하나를 만들어 `LabelingPage`에 전달 |
| `front/labeling_page.py` | `SegmentExporter` | "최종 저장" 누를 때마다 `SegmentExporter(self.trial, self.exporter.session_dir)`로 새 인스턴스를 만듦(아래 "동시성" 참고) |
| `front/export_worker.py` | `SegmentExporter` | 백그라운드 스레드에서 `export_draft()`를 반복 호출 |

## `SegmentNamer`

시나리오별 독립 카운터로 세그먼트 폴더 이름을 만든다.

- `distraction`/`drowsiness`: `{scenario}_segment{NNN:03d}` (카운터는 시나리오별로
  완전히 독립).
- `cognitive`: 카운터를 안 쓰고 `next_name()`에 넘겨받은 `cognitive_task_name`
  (`pre_nback1` 등)을 그대로 폴더명으로 씀.

`__init__(session_dir)`이 `session_dir/{scenario}/`를 스캔해서 이미 있는
`{scenario}_segment(\d+)` 폴더 중 최댓값부터 카운터를 이어간다. 항상 0부터
시작하면, 라벨링을 하다가 앱을 껐다 나중에 같은 트라이얼을 다시 열었을 때 새
`segment001`이 이전에 저장해둔 `segment001`을 조용히 덮어쓰는 문제가 있어서
디스크 스캔 기반으로 바뀜.

## `SegmentExporter.__init__(trial, session_dir)`

- `self.namer = SegmentNamer(self.session_dir)`.
- `annotations/{scenario}.csv` 3개를 `Scenario` enum을 순회하며 없으면 헤더만
  써서 미리 만들어둠(`ANNOTATION_CSV_FIELDS = ["segment_name", "segment_dir",
  "start_ts", "end_ts", "label"]`).
- `_camera_index_cache`/`_audio_index_cache`/`_radar_index`: 스트림당 인덱스를
  한 번만 만들면 되므로(같은 인스턴스로 여러 draft를 연달아 export할 때) 캐시.
- `self.export_warnings: list[str] = []`: `_write_video_cut`이 빠른 탐색 대신
  안전한 순차 디코딩으로 폴백한 경우를 기록해두는 리스트. `front/`가 export
  배치를 시작하기 전 비워두고, 끝난 뒤 이 리스트를 읽어서 라벨러에게 경고
  메시지로 보여준다(`front/labeling_page.py._finish_export_ui`).

## `export_draft(draft, cognitive_task_name=None, source_window=None, on_progress=None)`

한 draft를 실제로 잘라서 저장하는 진입점. 반환값은 만들어진 `segment_dir` 경로.

1. `SegmentNamer.next_name()`으로 세그먼트 이름/경로 결정, 하위 폴더(`camera`,
   `audio`, `physio_watch`, `radar`, `imu`) 미리 생성.
2. `_export_cameras` -> `_export_audio` -> `_export_imu`/`_export_watch` ->
   `_export_radar` 순서로 각 센서를 자름. 각 단계 전에 `on_progress` 콜백을
   호출해서 어떤 스트림을 처리 중인지 문자열로 알린다.
3. `annotation.json` 저장 - `label_fields`/`is_free_text_override`뿐 아니라
   `source_window.extra`(survey json 원본 필드, 예: `distraction_task_text`,
   `kss_score`)까지 `survey_extra` 키로 그대로 보존한다.
4. `annotations/{scenario}.csv`에 한 줄 추가. 이 파일이 없으면(수동 삭제 등)
   `export_draft` 호출마다 다시 만든다 - 실제 센서 파일은 전부 정상적으로
   써진 뒤 이 마지막 csv 기록 단계에서만 실패해서 export 전체가 실패한 것처럼
   보이는 문제가 있었던 부분.

`on_progress`는 평범한 콜러블(Qt 시그널이 아님) - `back/`은 Qt에 의존하면 안 되는
계층이라, `front/export_worker.py`의 `ExportWorker`가 이 콜러블을 Qt 시그널로
다시 감싸서 UI에 전달한다.

## 카메라 export

- `_get_camera_index`: 스트림 키(`(position, modality)`)별로 `CameraTimestampIndex`를
  캐시해서 만듦.
- `_export_cameras`: 트라이얼에 있는 모든 카메라 스트림을 순회, 각각
  `index.time_range_to_file_ranges(draft.start_ts, draft.end_ts)`로 파일 범위
  목록을 구해서 `_write_video_cut`에 넘김(비어있으면 - 이 구간에 실제 프레임이
  하나도 없으면 - 파일 자체를 안 만듦). `road` 포지션 스트림은 `flip_180=True`로
  넘겨서 물리적으로 180도 돌아간 채 장착된 카메라를 보정한다.
- `_write_video_cut(file_ranges, t_start, t_end, out_path, stream_label,
  flip_180)`: `file_ranges`의 각 `(path, local_start, local_end, 절대시작,
  절대끝, fps)`를 순서대로 처리한다. 실제 구간을 쓰는 부분은 기존과 동일:
  - `local_start > 0`이면 `cap.set(POS_FRAMES, local_start)`으로 먼저 탐색한
    뒤, 실제 도달한 위치(`cap.get(POS_FRAMES)`)가 `local_start` 이하인지 확인.
  - 이하라면 그 위치부터 순차 디코딩으로 나머지를 채움(빠른 경로).
  - 초과했다면(탐색이 요청 지점을 넘어서 정확도가 깨질 수 있는 상황) 프레임
    0부터 순차 디코딩으로 다시 시작하고, `self.export_warnings`에 기록.
  - `local_start`~`local_end` 구간의 프레임만 `writer.write()`(`flip_180`이면
    `cv2.rotate(ROTATE_180)` 적용 후).

  **여기에 세그먼트 사이 공백을 메우는 처리가 추가됐다** - 어느 조각의
  절대시작이 지금까지 쓴 위치(`cursor_ts`)보다 뒤라면(이 스트림 자체에
  공백이 있다는 뜻), 그 차이(`gap`)만큼:
  - 직전 조각이 있었으면(`prev_last_frame`) 공백을 반으로 나눠 앞쪽 절반은
    `write_repeated(prev_last_frame, ...)`로 직전 조각의 마지막 프레임을,
    뒤쪽 절반은 `_peek_frame(path, local_start)`로 읽은 이번 조각의 첫
    프레임을 반복해서 채운다 - 재생 중 `CameraTimestampIndex.frame_at_time()`이
    공백을 "더 가까운 쪽 경계 프레임"으로 클램프하는 것과 정확히 같은
    원칙(`technical_reference.md` 2부 17번).
  - 직전 조각이 없으면(요청 구간 맨 앞이 공백) 이번 조각의 첫 프레임으로
    공백 전체를 채운다.
  - 각 실제 조각을 다 쓴 뒤 그 조각의 마지막 프레임을 `prev_last_frame`으로
    기억해뒀다가, 다음 공백이나 맨 뒤 공백(마지막 조각 뒤에 요청 구간 끝까지
    남는 공백)을 채울 때 재사용한다.
  - `_peek_frame(path, local_idx)`: 딱 한 프레임만 읽는 가벼운 헬퍼(seek 후
    바로 read) - 위의 seek+검증+폴백 최적화와는 별개로, 경계 프레임 하나만
    필요할 때 씀. 항상 **회전 적용 전 원본** 프레임을 반환하고, 실제 반복
    출력 시점(`write_repeated`)에서 `flip_180`을 적용한다 - 메인 루프에서
    실제로 쓴 프레임을 재사용하는 `prev_last_frame`도 반드시 회전 전 원본을
    저장해야 한다(이미 회전된 프레임을 다시 회전시키면 원상복구되는 버그가
    실제로 있었고, 회전 전 원본을 저장하도록 고쳐서 해결됨).

## 오디오 export

- `_get_audio_index`: 마이크 이름별로 `AudioTimestampIndex` 캐시.
- `_reference_camera_segment_starts(expected_count)`: `_CAMERA_REFERENCE_PRIORITY`
  (`driver_rgb` 최우선) 순서로 카메라 스트림을 확인해서, 세그먼트 개수가
  `expected_count`와 일치하는 첫 스트림의 `segment_starts`를 반환. 여러 카메라
  스트림 중 아무거나 쓰지 않고 고정 우선순위를 쓰는 이유는 카메라마다 fps 실측
  오차가 미세하게 달라서, 매번 다른 스트림을 기준으로 삼으면 세그먼트 판단이
  흔들릴 수 있기 때문.
- `_export_audio`: 마이크마다 `reference_starts`를 `lambda n=...:
  self._reference_camera_segment_starts(n)`로 감싸서 `_get_audio_index`에
  넘긴다 - 콜러블로 넘기는 이유는 `AudioTimestampIndex`가 자기 데이터로 이미
  충분한 경우(대부분) 이 콜러블 자체를 호출하지 않게 하기 위해서다(카메라
  스트림 인덱스를 새로 만드는 건 대용량 csv 파싱이 필요해서 비용이 크다).
  `time_range_to_file_ranges`로 얻은 조각들을 `soundfile.SoundFile.seek()` +
  `read()`로 읽으면서, **조각 사이/앞/뒤에 공백이 있으면 그 절대시각 차이만큼
  무음(`np.zeros`, 채널 수는 첫 조각을 미리 열어서 확인)을 끼워 넣은 뒤**
  전부 이어붙여(`np.concatenate`) 한 번에 `sf.write()`. 이 구간에 실제
  오디오가 하나도 없으면(`file_ranges`가 비어있으면) 파일 자체를 안 만들고,
  일부라도 있으면 항상 `draft.end_ts - draft.start_ts` 길이 그대로 나온다
  (`technical_reference.md` 2부 17번).

## IMU/워치 export

- `_export_imu`/`_export_watch`: `TrialData.imu`/`watch`(각각 `dict[str,
  list[Path]]`)를 순회하며 `_filter_csv_by_time`을 호출.
- `_filter_csv_by_time(csv_paths, t_start, t_end, out_path, ts_col_candidates=
  ("timestamp", "t_sec"))`: 같은 센서의 세그먼트별 csv 파일들을 전부 열어서
  `t_start <= 시각 <= t_end`인 행만 모아 하나의 csv로 합친다. 파일 하나만 보지
  않고 리스트 전체를 순회하는 이유는, 라벨 구간이 세그먼트 경계에 걸쳐 있을 때
  한 파일만 보면 그 구간이 다른 세그먼트에 있는 경우 조용히 빈 결과가 나가기
  때문. `timestamp`/`t_sec` 두 컬럼명을 다 시도하는 이유는 워치 csv의 실제
  컬럼명이 하드웨어로 확정 검증되지 않았기 때문(방어적 처리).

## 레이더 export

- `_get_radar_index`: `TrialData.radar["raw_dir"]`로 `RadarTimestampIndex`를
  1회 생성해 캐시.
- `_export_radar`: `index.time_range_to_frames(start_ts, end_ts)`로 얻은
  `RadarFrame` 리스트를 순회하며, 각 프레임의 원본 `.bin` 파일에서
  `offset_int16_before * 2` 바이트 위치로 seek해서 `num_int16 * 2` 바이트를
  읽어 새 `radar_raw.bin`에 이어붙이고, 새 `radar_frame_index.csv`에 재번호를
  매겨 기록한다(`new_offset_int16`이 0부터 다시 누적됨 - 원본 파일의 절대
  오프셋이 아니라 새로 만든 파일 안에서의 상대 오프셋). 구간 중간에 레이더
  설정(`cfg`)이 바뀐 경우를 대비해, 사용된 cfg 전부를 sha256 기준 중복 제거해서
  보존한다(하나면 `used_cfg.cfg`, 여러 개면 `used_cfg_0.cfg`, `used_cfg_1.cfg`, ...).

## 동시성 - 매번 새 인스턴스를 만드는 이유

세션 하나에 `SegmentExporter`가 원래 하나만 있고(`front/main_window.py`가 세션
선택 시 1회 생성) 세 시나리오 페이지가 이걸 공유하는 구조였는데, 이러면 서로
다른 시나리오에서 동시에 "최종 저장"을 누를 때 `_camera_index_cache`,
`export_warnings`, `SegmentNamer._counters` 같은 공유 가변 상태를 두 스레드가
동시에 건드리는 경쟁 상태가 생길 수 있다. `front/labeling_page.py`가 "최종
저장"을 누를 때마다 `SegmentExporter(self.trial, self.exporter.session_dir)`로
독립된 인스턴스를 새로 만들어서 이 문제를 없앴다 - `SegmentNamer`가 이미 디스크
스캔 기반이라 매번 새 인스턴스를 만들어도 세그먼트 번호가 꼬이지 않는다는 점을
근거로 안전성이 성립한다.
