# `back/radar_index.py`

`radar/radar_raw/seg{NNN}/` 폴더들을 스캔해서 프레임 단위 절대시각 인덱스를
만든다. 카메라/오디오와 달리 `back/session_loader.py`가 개별 파일 목록을 미리
만들어주지 않고 디렉토리 경로만 넘겨주므로(`TrialData.radar["raw_dir"]`), 이
모듈이 폴더 스캔부터 직접 한다.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `back/segment_exporter.py` | `RadarTimestampIndex` | export 시 라벨 구간에 해당하는 레이더 프레임을 잘라냄 |

## 원본 파일 구조 (세그먼트 하나, `seg001` 예시)

```
radar_raw/seg001/
  radar_data_raw_int16_<timestamp>.bin   # int16 원시 IQ 데이터, 프레임들이 연속 배치
  radar_frame_index_<timestamp>.csv      # frame_idx, ros_time_sec, kst_time,
                                          # offset_int16_before, num_int16,
                                          # shape_chirps_rx_adc, frame_time_s, sample_rate_ksps
  used_cfg.cfg                           # mmWave 센서 설정 스냅샷 (TI SDK 03.05, xWR68xx)
  used_cfg_sha256.txt                    # cfg 무결성 체크섬
  radar_capture_summary_<timestamp>.json # 캡처 메타 요약 (frames, shape, range/velocity res 등)
```

프레임의 바이트 위치는 `offset_int16_before`(int16 단위) × 2 = byte offset, 길이는
`num_int16` × 2 bytes. 세그먼트 폴더 하나 안에서는 프레임이 시간순으로 연속
배치되어 있다(offset 증가폭이 `num_int16`으로 항상 일정함을 실측 확인).

세그먼트 폴더마다 자기 `used_cfg.cfg` 스냅샷을 따로 가지므로, 라벨 구간이 서로
다른 cfg를 쓴 두 세그먼트에 걸치면(레이더 설정이 중간에 바뀐 경우) 두 cfg를 모두
보존해서 내보낸다(`back/segment_exporter.py._export_radar`).

## `RadarFrame` (dataclass)

프레임 하나를 나타내는 레코드: `bin_path`, `local_frame_idx`, `t_sec`,
`offset_int16_before`, `num_int16`, `cfg_path`, `cfg_sha256`, `shape`(`shape_chirps_rx_adc`
컬럼 원본 문자열).

## `RadarTimestampIndex`

### `__init__(radar_raw_dir)` / `_load()`

`radar_raw_dir` 아래 `seg`로 시작하는 디렉토리를 이름순으로 정렬해서 각각 스캔한다.
세그먼트 폴더마다:
1. `radar_frame_index_*.csv`와 `radar_data_raw_int16_*.bin`을 `glob`으로 찾는다
   (둘 중 하나라도 없으면 그 세그먼트는 건너뜀).
2. `used_cfg_sha256.txt`가 있으면 첫 토큰을 읽어 체크섬으로 보관.
3. csv를 한 행씩 읽어 `RadarFrame`을 만들어 `self.frames`에 추가한다 -
   프레임 단위로 전체를 다 메모리에 올리는 방식(카메라/오디오처럼 세그먼트
   시작 시각만 구하고 나머지는 계산으로 구하는 방식이 아니라, 레이더는 프레임
   개수가 카메라보다 훨씬 적어서 전부 읽어도 무리가 없다는 전제).

세그먼트 폴더 순서가 곧 시간순이라고 가정하지만, 혹시 어긋나는 경우를 대비해
전체 스캔이 끝난 뒤 `self.frames.sort(key=lambda fr: fr.t_sec)`로 절대시각 기준
재정렬한다. 정렬 기준 시각 컬럼은 `ros_time_sec`.

### `time_range_to_frames(t_start, t_end) -> list[RadarFrame]`

`bisect.bisect_left`/`bisect_right`로 정렬된 `self._t_secs`(각 프레임의 `t_sec`만
뽑은 리스트)에서 이분 탐색해 `[t_start, t_end]` 범위의 `RadarFrame`들을 슬라이스로
반환한다. 카메라/오디오의 `time_range_to_file_ranges`가 (파일 경로, local
start, local end) 튜플을 반환하는 것과 달리, 여기는 프레임 객체 자체를 그대로
반환한다 - `back/segment_exporter.py._export_radar`가 이 프레임들의 `bin_path`/
`offset_int16_before`/`num_int16`을 이용해 원본 `.bin` 파일에서 직접 바이트를
읽어 잘라낸다.
