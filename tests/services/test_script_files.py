import pytest
from pathlib import Path
from kindling.services.script_files import (
    MAX_FILE_BYTES,
    validate_path,
    list_files,
    read_file,
    write_file,
    delete_file,
)


def test_validate_path_accepts_relpath():
    assert validate_path("main.py") == "main.py"
    assert validate_path("src/utils.py") == "src/utils.py"


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "foo\0bar", "", "a//b"])
def test_validate_path_rejects(bad):
    # All five bad inputs should raise ValueError. We don't pin a single
    # regex because the error message differs by failure mode, but we do
    # check that ValueError is raised (stricter than a bare `with
    # pytest.raises(...)` because it is explicit about the exception
    # type and rejects BaseException noise from coroutine warnings).
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


# --- New tests for the review findings -------------------------------


def test_symlink_inside_script_dir_pointing_outside_is_rejected(tmp_path: Path):
    """A symlink inside script_dir that resolves outside the directory
    must be rejected — protects against the startswith prefix-bypass
    and the symlink-escape vector."""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("top secret")

    # Put a symlink INSIDE script_dir that points OUTSIDE.
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "leak.py").symlink_to(secret)

    with pytest.raises(ValueError, match="escapes script directory"):
        read_file(script_dir, "leak.py")

    with pytest.raises(ValueError, match="escapes script directory"):
        delete_file(script_dir, "leak.py", entrypoint="main.py")


def test_prefix_bypass_path(tmp_path: Path):
    """A sibling directory whose name starts with script_dir's name
    must NOT be reachable. With the old startswith check, /tmp/foo_bar/x
    would have been accepted when script_dir resolved to /tmp/foo."""
    parent = tmp_path
    # Create two directories whose names share a prefix.
    a = parent / "foo"
    b = parent / "foo_bar"
    a.mkdir()
    b.mkdir()

    # Bypass: walk up one component and append foo_bar/x.py.
    # This validates the is_relative_to semantics: validate_path()
    # blocks ".." traversal, so we exercise the symlink prefix variant.
    (b / "x.py").write_text("evil")

    # Symlink foo -> foo_bar so a path inside "foo" walks to a sibling.
    (a / "evil.py").symlink_to(b / "x.py")

    with pytest.raises(ValueError):
        read_file(a, "evil.py")


def test_write_file_max_bytes_enforced(tmp_path: Path):
    """Content larger than MAX_FILE_BYTES must be rejected before any
    disk write happens."""
    too_big = "x" * (MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError, match=f"exceeds {MAX_FILE_BYTES}"):
        write_file(tmp_path, "main.py", too_big)
    # Nothing should have been written.
    assert not (tmp_path / "main.py").exists()


def test_list_files_entrypoint_first_sort_order(tmp_path: Path):
    """The entrypoint file must appear at index 0 of the returned
    list, before the alphabetically-sorted remainder."""
    (tmp_path / "z_last.py").write_text("z")
    (tmp_path / "a_mid.py").write_text("a")
    (tmp_path / "main.py").write_text("m")

    files = list_files(tmp_path, entrypoint="main.py")
    paths = [f.path for f in files]
    assert paths[0] == "main.py"
    # Remaining entries come after the entrypoint.
    assert paths[1:] == sorted(paths[1:])
    # And entrypoint does not appear again later.
    assert paths.count("main.py") == 1


def test_write_file_to_nested_path(tmp_path: Path):
    """write_file must create intermediate directories and then
    round-trip through read_file."""
    write_file(tmp_path, "src/utils.py", "def hi(): return 'hi'\n")
    assert read_file(tmp_path, "src/utils.py") == "def hi(): return 'hi'\n"
    assert (tmp_path / "src").is_dir()
    assert (tmp_path / "src" / "utils.py").is_file()
