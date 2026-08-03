"""
프로젝트 안의 .py 파일들을 순회하며 각 파일 맨 위 모듈 docstring(파일 역할 설명)을
모아서 보여주는 스크립트. 코드를 실행하지 않고 ast로 정적 파싱만 함. 결과는
콘솔이 아니라 스크립트와 같은 위치의 txt 파일로 저장.

사용법:
    python describe_files.py            # back/, front/, 루트 .py 전부
    python describe_files.py back        # back/ 아래만
    python describe_files.py front/widgets
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_TARGETS = ["back", "front", "."]  # "." = 루트 바로 아래 .py들(하위 폴더 제외)


def module_docstring(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        return f"[파싱 실패: {e}]"
    doc = ast.get_docstring(tree)
    return doc.strip() if doc else None


def iter_py_files(target: str):
    target_path = ROOT / target
    if target == ".":
        yield from sorted(ROOT.glob("*.py"))
    elif target_path.is_dir():
        yield from sorted(target_path.rglob("*.py"))
    elif target_path.is_file():
        yield target_path


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TARGETS
    seen = set()
    lines: list[str] = []

    for target in targets:
        for path in iter_py_files(target):
            if path in seen or "__pycache__" in path.parts:
                continue
            seen.add(path)
            rel = path.relative_to(ROOT)
            doc = module_docstring(path)
            lines.append(f"{'=' * 80}\n{rel}\n{'=' * 80}")
            lines.append(doc if doc else "(docstring 없음)")
            lines.append("")

    out_path = ROOT / "describe_files_output.txt"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"결과 저장됨: {out_path}")


if __name__ == "__main__":
    main()
