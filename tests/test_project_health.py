from pathlib import Path
import py_compile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_python_sources_compile() -> None:
    source_files = [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if ".git" not in path.parts
        and "__pycache__" not in path.parts
        and "Jarvis-the-latest-version" not in path.parts
    ]

    assert source_files
    for source_file in source_files:
        py_compile.compile(str(source_file), doraise=True)
