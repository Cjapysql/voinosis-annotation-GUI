# `back/video_codec.py`

OS/OpenCV 빌드마다 mp4 인코딩이 실제로 되는 fourcc가 달라서, 여러 후보를
순서대로 시도해보고 실제로 열리는 첫 번째 코덱을 골라 쓰는 유틸.

## 이 파일을 가져다 쓰는 곳

| 파일 | 가져다 쓰는 것 | 용도 |
|---|---|---|
| `back/segment_exporter.py` | `make_video_writer` | `_write_video_cut`이 실제로 mp4 파일을 쓸 `cv2.VideoWriter`를 만들 때 사용 |

## `get_working_fourcc(sample_size=(64, 48), fps=30.0) -> str`

OS별 후보 목록(`_CANDIDATES_BY_OS`: Windows는 `avc1`/`H264`/`mp4v` 순,
Darwin(macOS)은 `avc1`/`mp4v`, Linux는 `mp4v`/`avc1`/`H264`)을 순서대로 시도한다.
각 후보에 대해 임시 파일에 실제로 `cv2.VideoWriter`를 열어보고(`writer.isOpened()`),
성공하는 첫 번째 코덱을 반환한다. 어느 후보도 안 되면 마지막 안전값으로
`mp4v`를 반환(대부분의 빌드에서 최소한 열리기는 함).

결과는 프로세스 전역 `_cached_fourcc`에 캐시되어, 이후 호출은 실제 시도 없이
바로 반환된다 - 매번 실제로 파일을 만들어보는 비용을 한 프로세스당 1회로
제한.

이 프로젝트의 참고 빌드 환경(Ubuntu 24, OpenCV 4.13)에서는 `mp4v`가 확인된
동작 코덱이다.

## `make_video_writer(out_path, fps, frame_size) -> cv2.VideoWriter`

`get_working_fourcc()`로 코덱을 고른 뒤 그걸로 `cv2.VideoWriter`를 만들어 반환.
`back/segment_exporter.py._write_video_cut`이 스트림 하나를 자를 때 프레임이
처음 나온 시점에(프레임 크기를 알아야 `VideoWriter`를 만들 수 있으므로) 이
함수를 호출한다.
