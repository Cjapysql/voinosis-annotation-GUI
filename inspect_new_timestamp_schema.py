"""
신규 폴더 구조(seg{NNN} 하위폴더) timestamp csv 스키마를 pandas DataFrame으로
눈으로 확인하기 위한 임시 스크립트. session_loader.py/timestamp_index.py는
전혀 건드리지 않고, 그냥 csv를 읽어서 보여주기만 함. 결과는 콘솔이 아니라
스크립트와 같은 위치의 txt 파일로 저장.

사용법 (주피터 셀에 그대로 붙여넣거나 python으로 실행):
    python inspect_new_timestamp_schema.py
"""
from pathlib import Path

import pandas as pd

TRIAL_DIR = "/home/voinosis/Downloads/radar_ws/bags/id9276_trial3_20260727_162156_total_test"

camera_csv = f"{TRIAL_DIR}/camera/rgb/seg001/front_color_timestamps.csv"
audio_csv = f"{TRIAL_DIR}/audio/seg001/ecms1_audio_timestamps.csv"

lines: list[str] = []


def log(msg="") -> None:
    lines.append(str(msg))


log("=" * 80)
log(f"카메라: {camera_csv}")
log("=" * 80)
df_cam = pd.read_csv(camera_csv)
log(df_cam.dtypes)
log()
log(df_cam.head(10))
log("...")
log(df_cam.tail(5))
log(f"\n총 {len(df_cam)}행")
if "복제프레임여부" in df_cam.columns:
    log(f"복제프레임여부 값 분포:\n{df_cam['복제프레임여부'].value_counts()}")
if "프레임종류" in df_cam.columns:
    log(f"프레임종류 값 분포:\n{df_cam['프레임종류'].value_counts()}")

log()
log("=" * 80)
log(f"오디오: {audio_csv}")
log("=" * 80)
df_audio = pd.read_csv(audio_csv)
log(df_audio.dtypes)
log()
log(df_audio.head(10))
log("...")
log(df_audio.tail(5))
log(f"\n총 {len(df_audio)}행")

out_path = Path(__file__).resolve().parent / "inspect_new_timestamp_schema_output.txt"
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"결과 저장됨: {out_path}")
