# docs/ 폴더 안내

이 폴더는 `back/`, `front/` 소스 파일 하나당 문서 하나씩 담고 있다. 프로젝트
전체를 처음부터 훑는 진입점은 이 폴더가 아니라 저장소 최상위 `README.md`다 —
거기서 "문서 지도" 절을 먼저 읽을 것.

## 여기 뭐가 있는지

- `back_*.md`, `front_*.md`, `entry_points.md` — 파일별 상세 문서 (총 22개).
  각 문서는 "이 파일을 가져다 쓰는 곳"(import/사용처) 표로 시작해서, 핵심
  메서드의 동작 원리, 그리고 관련된 `../technical_reference.md` 2부 절
  번호로의 링크를 포함한다.
- `module_map.html` — 22개 파일의 의존 관계를 topological depth 기준 6단계로
  그린 다이어그램 + 추천 읽는 순서. 브라우저로 열어서 볼 것. `module_map.png`/
  `module_map.jpg`는 같은 페이지를 이미지로 캡처해둔 것(브라우저 없이 빠르게
  볼 때용).

## 파일명 ↔ 소스 경로 대응

`back_xxx.md` → `back/xxx.py`, `front_xxx.md` → `front/xxx.py`,
`front_widgets_xxx.md` → `front/widgets/xxx.py`. `entry_points.md`만 예외로
`front/main.py`와 `run_app.py` 둘을 함께 다룬다.

## 문서를 갱신해야 하는 시점

해당 소스 파일의 동작(입출력, 예외 처리, 다른 파일과의 관계)이 바뀌면 같은
작업 안에서 이 폴더의 대응 문서도 갱신한다. 설계 결정이 바뀌었거나 그
과정에서 버그를 발견/수정했다면 `../technical_reference.md` 2부에 해당
내용을 추가/갱신하고, 이 폴더의 문서에서 절 번호로 링크한다.
