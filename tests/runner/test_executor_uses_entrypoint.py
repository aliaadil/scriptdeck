from pathlib import Path

from kindling.runner.python_runner import PythonRunner


def test_runner_build_command_takes_entrypoint_path(tmp_path: Path):
    runner = PythonRunner()
    script_dir = tmp_path / "scripts" / "1"
    script_dir.mkdir(parents=True)
    (script_dir / "main.py").write_text("x")
    entrypoint_file = script_dir / "run.py"
    entrypoint_file.write_text("y")
    cmd = runner.build_command(
        interpreter=Path("/usr/bin/python3"),
        source_path=entrypoint_file,
        env={},
    )
    assert cmd[0] == "/usr/bin/python3"
    assert cmd[1] == str(entrypoint_file)
