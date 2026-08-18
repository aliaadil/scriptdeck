import pytest
from pathlib import Path
from kindling.services.script_files import (
    validate_path, list_files, read_file, write_file, delete_file,
)


def test_validate_path_accepts_relpath():
    assert validate_path("main.py") == "main.py"
    assert validate_path("src/utils.py") == "src/utils.py"


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "foo\0bar", "", "a//b"])
def test_validate_path_rejects(bad):
    with pytest.raises(ValueError):
        validate_path(bad)


def test_list_files(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('x')")
    (tmp_path / ".env").write_text("")
    files = list_files(tmp_path, entrypoint="main.py")
    names = {f.path for f in files}
    assert names == {"main.py", ".env"}


def test_write_and_read(tmp_path: Path):
    write_file(tmp_path, "main.py", "hi")
    assert read_file(tmp_path, "main.py") == "hi"


def test_delete_entrypoint_refuses(tmp_path: Path):
    (tmp_path / "main.py").write_text("x")
    with pytest.raises(ValueError, match="entrypoint"):
        delete_file(tmp_path, "main.py", entrypoint="main.py")


def test_delete_other(tmp_path: Path):
    (tmp_path / "main.py").write_text("x")
    (tmp_path / "util.py").write_text("y")
    delete_file(tmp_path, "util.py", entrypoint="main.py")
    assert not (tmp_path / "util.py").exists()