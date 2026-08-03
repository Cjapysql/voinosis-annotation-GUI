"""
비디오/오디오 세그먼트 파일들을 직접 열어서 실제 프레임(샘플) 수, fps/sample rate,
길이, timestamp csv 행 개수를 확인하는 진단 스크립트. 코드 수정 없이 그냥 눈으로
확인하고 싶을 때 씀. 결과는 콘솔이 아니라 스크립트와 같은 위치의 txt 파일로 저장.

사용법:
    python check_av_frames.py <home_dir> <trial_folder_name>

예:
    python check_av_frames.py /home/voinosis/Downloads/radar_ws \
        id12345_trial2_20260615_152028_승우
"""
import csv
import sys
import wave
from pathlib import Path
from typing import Callable

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from back.session_loader import SessionLoader
from back.timestamp_index import CameraTimestampIndex

Logger = Callable[[str], None]


def _count_csv_rows(csv_path) -> int:
    if not csv_path:
        return 0
    with open(csv_path, "r", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def _csv_time_span(csv_path) -> tuple[int, float] | None:
    """(행 개수, 첫 로그~마지막 로그 사이 실제 경과 시간(초)). 오디오는 행 하나가
    raw 샘플 1개가 아니라 가변 길이 청크라서, 행 개수를 샘플 수와 직접 비교하는 건
    의미가 없다 - 대신 시간 스팬(초 단위)끼리 비교해야 한다.
    오디오 timestamp csv 컬럼: 저장오디오청크번호(정렬 순번), 동기화기준시각_sec(정렬 기준 시각)."""
    if not csv_path:
        return None
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["저장오디오청크번호"]))
    if not rows:
        return None
    span = float(rows[-1]["동기화기준시각_sec"]) - float(rows[0]["동기화기준시각_sec"])
    return len(rows), span


def check_camera_stream(log: Logger, name: str, stream) -> None:
    log(f"\n=== 카메라: {name} ===")

    total_frames = 0
    total_csv_rows = 0
    for seg_num, path, ts_path in stream.segment_files:
        cap = cv2.VideoCapture(str(path))
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        duration = nframes / fps if fps else 0.0
        total_frames += nframes
        n_rows = _count_csv_rows(ts_path)
        total_csv_rows += n_rows
        csv_note = "csv 없음" if ts_path is None else f"자기 timestamp csv 행 개수={n_rows}"
        log(f"  seg{seg_num} ({path.name}): 프레임 수={nframes}, fps(cv2 신고값)={fps:.4f}, "
            f"길이={duration:.2f}s, {csv_note}")

    log(f"  세그먼트 전체 합산 프레임 수: {total_frames}  (csv 행 개수 합계와 차이: {total_csv_rows - total_frames:+d})")

    idx = CameraTimestampIndex(stream.segment_files)
    log(f"  보정된 fps(실측 기반): {[round(f, 4) for f in idx._segment_fps]}")
    log(f"  세그먼트별 절대 시작 시각: {idx.segment_starts}")

    # 세그먼트마다 자기 timestamp csv를 따로 갖는 경우(신 구조)엔 그 csv 전체가
    # 그대로 그 세그먼트 것으로 신뢰되지만, 그래도 그 csv 자체 안에서 로깅이
    # 중간에 끊긴 흔적(gap)이 있는지는 참고삼아 확인해볼 가치가 있다. 여러
    # 세그먼트가 csv 하나를 공유하는 경우(구 구조)엔 이 gap이 바로 세그먼트
    # 경계 판단 근거였던 것이라 특히 중요.
    for i, t_secs in enumerate(idx._segment_t_secs):
        seg_num, _path = idx.segment_files[i]
        if len(t_secs) < 2:
            log(f"  seg{seg_num}: 실측 timestamp {len(t_secs)}개 (gap 분석 불가)")
            continue
        gaps = [(j, t_secs[j] - t_secs[j - 1]) for j in range(1, len(t_secs))
                if t_secs[j] - t_secs[j - 1] > idx.GAP_THRESHOLD_SEC]
        note = "  <- 이 세그먼트 자체 csv 안에서 로깅이 중간에 끊긴 걸로 보임" if gaps else ""
        log(f"  seg{seg_num}: 실측 timestamp {len(t_secs)}개, 자체 gap 개수={len(gaps)}{note}")
        for j, d in gaps[:20]:
            log(f"    행 {j}에서 {d:.2f}초 점프 (t_sec={t_secs[j-1]:.3f} -> {t_secs[j]:.3f})")


def check_audio_stream(log: Logger, name: str, stream) -> None:
    log(f"\n=== 오디오: {name} ===")

    total_actual_duration = 0.0
    total_span = 0.0
    have_span = False
    for seg_num, path, ts_path in stream.segment_files:
        span_info = _csv_time_span(ts_path)

        with wave.open(str(path), "rb") as wf:
            declared_nframes = wf.getnframes()  # wav 헤더에 적힌 값 (신뢰 안 함)
            rate = wf.getframerate()
            sampwidth = wf.getsampwidth()
            nchannels = wf.getnchannels()

            # 헤더 값을 안 믿고 끝까지 실제로 읽어서 진짜 샘플 수를 직접 셈
            actual_bytes = 0
            while True:
                chunk = wf.readframes(65536)
                if not chunk:
                    break
                actual_bytes += len(chunk)
            actual_nframes = actual_bytes // (sampwidth * nchannels)

        file_size = path.stat().st_size
        duration_declared = declared_nframes / rate if rate else 0.0
        duration_actual = actual_nframes / rate if rate else 0.0

        log(f"  seg{seg_num} ({path.name}):")
        log(f"    헤더에 선언된 샘플 수: {declared_nframes} (길이 {duration_declared:.2f}s)")
        log(f"    실제로 끝까지 읽어서 센 샘플 수: {actual_nframes} (길이 {duration_actual:.2f}s)")
        if actual_nframes != declared_nframes:
            log(f"    <- 불일치! 헤더보다 {actual_nframes - declared_nframes:+d} 샘플")
        log(f"    sample rate={rate}Hz, 채널={nchannels}, 파일 크기={file_size:,} bytes")

        if span_info:
            n_rows, span = span_info
            log(f"    자기 timestamp csv: 행 개수={n_rows} (참고용 - 청크라 샘플 수와 직접 비교 무의미), "
                f"시간 스팬={span:.2f}s  (실제 길이와 차이: {duration_actual - span:+.2f}s)")
            total_span += span
            have_span = True
        else:
            log("    timestamp csv 없음")

        total_actual_duration += duration_actual

    if have_span:
        log(f"  실제 오디오 총 길이 합계: {total_actual_duration:.2f}s  vs  csv 시간 스팬 합계: {total_span:.2f}s"
            f"  (차이: {total_actual_duration - total_span:+.2f}s)")


# 커맨드라인 인자 없이 그냥 실행(예: 주피터, IDE 실행 버튼)할 때 쓸 기본값.
# 인자를 주면 그쪽이 우선한다.
DEFAULT_HOME_DIR = "/home/voinosis/Downloads/radar_ws"
DEFAULT_TRIAL_FOLDER = "id9276_trial3_20260727_162156_total_test"


def main() -> None:
    if len(sys.argv) == 3:
        home_dir, trial_folder = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 1:
        home_dir, trial_folder = DEFAULT_HOME_DIR, DEFAULT_TRIAL_FOLDER
    else:
        print("사용법: python check_av_frames.py <home_dir> <trial_folder_name>")
        sys.exit(1)

    loader = SessionLoader(home_dir)
    trial = loader.load_trial(trial_folder)

    out_path = Path(__file__).resolve().parent / f"check_av_frames_{trial_folder}.txt"
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)

    for (position, modality), stream in trial.cameras.items():
        if stream.segment_files:
            check_camera_stream(log, f"{position}_{modality}", stream)

    for mic_name, stream in trial.audio.items():
        if stream.segment_files:
            check_audio_stream(log, mic_name, stream)

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"결과 저장됨: {out_path}")


if __name__ == "__main__":
    main()
