# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

DMS (Driver Monitoring System) Labeling Tool — a PySide6 desktop app for annotating multi-sensor
driving-session recordings (multiple cameras, audio, IMU, radar, watch) with three label scenarios:
`distraction`, `drowsiness`, `cognitive`. Confirmed label segments are cut from the raw sensor files at
frame/sample accuracy and exported to a structured output tree. Source comments and the README are in
Korean; when editing files, match the existing Korean comment style rather than switching to English.

## Documentation map

This repo carries more documentation than just this file — check it before assuming something is
undocumented:

- `docs/<module>.md` — one file per `back/`/`front/` source file (22 total), each with an "imported by"
  table and mechanism detail. Read the relevant one before touching a file.
- `docs/module_map.html` (`.png` is a static render of the same page) — dependency diagram across
  all 22 files plus a suggested reading order.
- `README.md` — human-facing overview/onboarding entry point; largely mirrors this file's Architecture and
  Domain-rules sections plus module tables.
- `DEPLOY.md` / `설치_안내.md` — building/distributing the packaged executable to non-developer labelers.

When a change alters architecture or a domain rule, update the matching section in this file and in
`README.md` (and the relevant `docs/*.md` entry) in the same change — these are treated as living docs,
not one-off write-ups.

## Commands

```bash
# Setup
sudo apt install ffmpeg          # required by OpenCV's VideoWriter (mp4v)
pip install -r requirements.txt

# Run the UI
cd front && python main.py /path/to/DMS_Actions.xlsx   # xlsx arg optional; without it, only "기타"(free-text) labeling is available

# Alternative entry point (same one PyInstaller builds from; adds sys.path handling)
python run_app.py [/path/to/DMS_Actions.xlsx]

# Build a single-file Linux executable for non-technical labelers (Docker, pinned to Ubuntu 22.04 — the
# oldest version labelers run — so glibc forward-compat covers newer versions too; host OS version doesn't
# matter). Output: dist/dms_labeling
./build_linux_2204.sh

# Windows executable: no local command — pushed via GitHub Actions (.github/workflows/build-windows.yml),
# either manually (workflow_dispatch) or on a v* tag push, since PyInstaller can't cross-compile.

# Diagnostic: inspect raw frame/sample counts for a trial without modifying anything
python check_av_frames.py <home_dir> <trial_folder_name>
```

See `DEPLOY.md` for the full build/distribution walkthrough (Linux Docker build, Windows CI, desktop-icon
registration via `assets/install_linux.sh`, and labeler-PC prerequisites).

There is no automated test suite, linter, or CI config in this repo. Validation has historically been done
via manual/offscreen smoke tests (see "Headless verification" below) — there is no `pytest`/`unittest`
command to run.

## Architecture

The codebase is a strict two-layer split:

- **`back/`** — pure data layer (parsing, alignment, cutting, storage). No Qt dependency; only
  `opencv-python`, `soundfile`, `openpyxl`, `numpy`. Usable standalone as a batch-processing library or
  from a different frontend.
- **`front/`** — PySide6 UI that imports `back` classes via `from back.xxx import yyy` and wires them to
  widgets/interaction. Never the reverse — `back` must not import from `front`.

### Data flow through `back/`

1. **`session_loader.py`** scans a raw trial folder (`<home>/bags/<trial>/...`) and groups files by stream
   into a `TrialData`: cameras (`{position}_{modality}_seg{NNN}.mp4` — position `front|behavior|road` →
   normalized `driver|behavior|road`, modality `color|infrared|depth` → normalized `rgb|infrared|depth`),
   audio (`{mic}_seg{NNN}.wav`), IMU, radar (`radar_raw/segNNN/`), watch CSVs, and survey JSON. Segment
   numbers may be non-contiguous (001, 003, 006...) because recording restarts add a new seg — only sort
   order is trusted, not the numeric value.
2. **`survey_parser.py`** turns survey JSON (`intro`, `cognitive_before_driving`/`cognitive_after_driving`,
   `driving`) into a list of `TaskWindow` objects (from `models.py`) — these are auto-generated markers
   drawn on the timeline *before* the labeler does anything, not something the labeler creates.
3. **`timestamp_index.py`** converts between absolute unix time and stream-local frame/sample indices
   (frames for camera, chunk→sample for audio), handling the seg-file stitching so multiple mp4/wav
   segments appear as one continuous virtual timeline. **`audio_stitcher.py`** and **`radar_index.py`**
   provide the equivalent alignment for their respective streams (radar uses `ros_time_sec` from
   `offset_int16` based indexing).
4. While labeling, confirmed timestamp+label pairs live only in **`draft_store.py`** (`LabelDraft`, local,
   freely editable) — nothing is cut yet.
5. On final commit, **`segment_exporter.py`** reads the drafts and performs the actual frame-accurate cut
   (re-encode, not `ffmpeg -ss` keyframe seeking) across every sensor simultaneously, writing to
   `session_XXX_id_XXX/{scenario}/{segment}/...`.
6. **`label_taxonomy.py`** loads `DMS_Actions.xlsx` into an Area→{verbs, nouns} structure that drives the
   distraction label form's dropdowns (with a "기타" free-text escape hatch on every categorical field).
7. **`video_codec.py`** auto-detects a working mp4 fourcc for the current OS (mp4v confirmed working on
   Ubuntu 24 / OpenCV 4.13 in the reference build environment).
8. **`coverage.py`** does a cheap, segment-granularity-only pass (first/last timestamp per segment CSV, no
   frame/sample-accurate indexing) to answer "does this sensor have any data near this range at all" —
   used for the "no data in this range" warning banner in the labeling UI, not for cutting.

### `front/` flow

`main.py` (or `run_app.py`, same entry, adds `sys.path` handling — what PyInstaller builds from) →
`MainWindow` (`main_window.py`) drives `StartPage` (pick `home_dir`/trial) → scenario selection →
`labeling_page_loader.py` runs the heavy pre-construction work (camera timestamp indices, audio stitching)
on a background thread so the scenario→labeling screen transition doesn't freeze the UI → `LabelingPage`
(`labeling_page.py`, the shared page for all three scenarios: timeline + 6-way video split + label form +
draft management), constructing one `DraftStore`/`SegmentExporter` pair per session. `stream_player.py`
maps absolute time → a frame for one camera stream (fast sequential playback vs. seek).
`playback_controller.py` uses the dashboard mic audio as the master clock to keep the 6 video panels in
sync (falls back to a `QTimer` if no audio track is available). `widgets/timeline_widget.py` renders task
window markers, draft segments, and the playhead. `widgets/video_panel.py` displays one camera panel,
distinguishing "this stream doesn't exist for this trial" from "stream exists but no frame at this instant
(gap)". `widgets/label_forms.py` implements the shared Area→Verb/Noun-hierarchy-plus-"기타" pattern per
scenario. On final save, `export_worker.py` runs `SegmentExporter.export_draft()` on a background `QThread`
(re-encoding can take seconds-to-tens-of-seconds per segment) and only calls `DraftStore.mark_committed()`
back on the main thread once it signals done, to avoid the two threads touching draft-store file I/O
concurrently.

### Domain rules that are load-bearing (don't relitigate without checking README.md / `models.py` docstring)

- All sensors align on a common unix time (`t_sec`); a label segment's absolute start/end cuts every
  sensor at once.
- Drowsiness window is always `driving_task.start_time - 60s` to `start_time` (fixed, not
  labeler-adjustable) — chosen so spoken survey answers don't bleed into the audio.
- `distraction` and `drowsiness`/`cognitive` differ in mutability: `distraction` sub-segments are freely
  labeler-defined (a single task window can be split into as many sub-segments as a compound instruction
  needs); `drowsiness` and `cognitive` windows are computed from survey JSON and locked
  (`TaskWindow`/`LabelDraft.boundaries_locked` — see `LabelingPage.boundaries_locked`).
- Segment numbering: `distraction_segmentNNN` and `drowsiness_segmentNNN` are independent counters per
  scenario; `cognitive` has no counter and instead uses fixed names
  `pre_nback1~3, pre_cbt1~3, post_nback1~3, post_cbt1~3`.
- Draft → commit is one-way: `DraftStore` holds editable timestamp+label state; only the "최종 저장" (final
  save) action invokes `SegmentExporter`, which is treated as an irreversible commit.
- Column names for watch CSVs (`timestamp` vs `t_sec`) are not confirmed against real hardware —
  `_filter_csv_by_time` defensively tries both; a real mismatch fails silently into an empty file rather
  than raising.
- Export-side padding: if a label segment's requested `[start_ts, end_ts]` only partially overlaps a
  sensor's actual recorded gap (not zero overlap — a segment with zero real data still produces no file at
  all, unchanged), that sensor's output is padded to the full requested duration rather than left short.
  Audio pads with real silence (`np.zeros`); video pads by repeating the nearer boundary frame, split at
  the gap's temporal midpoint — deliberately mirroring `CameraTimestampIndex.frame_at_time()`'s existing
  playback-time gap-clamping behavior rather than a simpler "always hold last frame" rule (explicit design
  choice).

### Headless verification (no display/audio device in the reference dev environment)

Historical validation used `QT_QPA_PLATFORM=offscreen` to construct all pages without a real display, plus
`widget.grab()` to save actual rendered PNGs, plus a PulseAndio `module-null-sink` to drive `QMediaPlayer`
through a real event loop and confirm `positionChanged` progresses. If you touch playback/timeline code and
have no display available, this is the pattern to reuse rather than assuming headless = untestable.

For `back/`-only changes (no Qt involved), the recurring pattern instead is calling the function directly
against a real trial's data (real segment CSVs, real mp4/wav — not synthetic) and checking the numeric
result (frame counts, byte offsets, computed timestamps) against an independently-computed expected value.
Because mp4 re-encoding is lossy, byte-identity checks don't work for video frames even when the source
content is genuinely unchanged — mean absolute pixel difference is used instead, with ~2-7 observed for
"same content, encoder noise" vs. ~26-30 for "actually different content".

## Known open items

- Watch CSV column names are unconfirmed against real device output.
- `distraction_task_id` → Area/Verb/Noun auto-prefill is intentionally not implemented (labeler picks
  manually using the task text hint); would need a mapping table to automate.
- `DISPLAY_STREAMS` in `front/labeling_page.py` controls which camera panels render — depth stream is
  currently not shown.
- `RadarTimestampIndex` re-sorts frames by `ros_time_sec` for safety, but if frames from different seg
  folders actually turn out to be interleaved on disk (shouldn't happen normally), per-frame reads would
  each trigger separate file I/O; batched contiguous-range reads would be the fix if this is ever observed.
