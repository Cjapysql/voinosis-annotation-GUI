"""
radar/radar_raw/segNNN/ 폴더들을 스캔해서 프레임 단위 절대시각 인덱스를 만든다.

실측 파일 구조 (seg001 예시):
  radar_raw/seg001/
    radar_data_raw_int16_<timestamp>.bin   # int16 원시 IQ 데이터, 프레임들이 연속 배치
    radar_frame_index_<timestamp>.csv       # frame_idx, ros_time_sec, kst_time,
                                             # offset_int16_before, num_int16,
                                             # shape_chirps_rx_adc, frame_time_s, sample_rate_ksps
    used_cfg.cfg                            # mmWave 센서 설정 스냅샷 (TI SDK 03.05, xWR68xx)
    used_cfg_sha256.txt                     # cfg 무결성 체크섬
    radar_capture_summary_<timestamp>.json  # 캡처 메타 요약 (frames, shape, range/velocity res 등)

프레임 바이트 위치는 offset_int16_before(int16 단위) * 2 = byte offset,
길이는 num_int16 * 2 bytes. 여러 seg 폴더에 걸쳐 있어도 각 폴더 안에서는
프레임이 시간순으로 연속 배치되어 있음 (offset 증가폭이 num_int16으로 항상 일정함을 실측 확인).

카메라와 달리 seg 폴더마다 자체 cfg 스냅샷을 갖고 있어서, 만약 라벨 구간이
서로 다른 cfg를 쓴 두 seg에 걸치면(레이더 설정이 중간에 바뀐 경우) 두 cfg를
모두 보존해서 내보낸다.
"""
import bisect
import csv as csv_mod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RadarFrame:
    bin_path: Path
    local_frame_idx: int
    t_sec: float
    offset_int16_before: int
    num_int16: int
    cfg_path: Path
    cfg_sha256: str
    shape: str


class RadarTimestampIndex:
    def __init__(self, radar_raw_dir: Path):
        self.radar_raw_dir = Path(radar_raw_dir)
        self.frames: list[RadarFrame] = []
        self._load()
        self._t_secs = [fr.t_sec for fr in self.frames]

    def _load(self):
        if not self.radar_raw_dir.exists():
            return
        seg_dirs = sorted(
            (p for p in self.radar_raw_dir.iterdir() if p.is_dir() and p.name.startswith("seg")),
            key=lambda p: p.name,
        )
        for seg_dir in seg_dirs:
            csv_path = next(seg_dir.glob("radar_frame_index_*.csv"), None)
            bin_path = next(seg_dir.glob("radar_data_raw_int16_*.bin"), None)
            cfg_path = seg_dir / "used_cfg.cfg"
            sha_path = seg_dir / "used_cfg_sha256.txt"
            if csv_path is None or bin_path is None:
                continue

            cfg_sha = ""
            if sha_path.exists():
                cfg_sha = sha_path.read_text(encoding="utf-8").split()[0]

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    self.frames.append(RadarFrame(
                        bin_path=bin_path,
                        local_frame_idx=int(row["frame_idx"]),
                        t_sec=float(row["ros_time_sec"]),
                        offset_int16_before=int(row["offset_int16_before"]),
                        num_int16=int(row["num_int16"]),
                        cfg_path=cfg_path if cfg_path.exists() else None,
                        cfg_sha256=cfg_sha,
                        shape=row.get("shape_chirps_rx_adc", ""),
                    ))

        # seg 폴더 순서가 곧 시간순이라고 가정되지만, 혹시 어긋나는 경우를 대비해
        # 최종적으로 절대시각 기준 재정렬
        self.frames.sort(key=lambda fr: fr.t_sec)
        self._t_secs = [fr.t_sec for fr in self.frames]

    def time_range_to_frames(self, t_start: float, t_end: float) -> list[RadarFrame]:
        lo = bisect.bisect_left(self._t_secs, t_start)
        hi = bisect.bisect_right(self._t_secs, t_end)
        return self.frames[lo:hi]
