import pytest

from kindling.runner.node_runner import NodeRunner
from kindling.runner.python_runner import PythonRunner
from kindling.runner.registry import RUNNERS, get_runner


def test_registry_has_python_and_node():
    assert "python" in RUNNERS
    assert "node" in RUNNERS
    assert isinstance(RUNNERS["python"], PythonRunner)
    assert isinstance(RUNNERS["node"], NodeRunner)


def test_get_runner_unknown():
    with pytest.raises(KeyError):
        get_runner("ruby")


def test_python_runner_artifact():
    r = PythonRunner()
    assert r.resolve_artifact_path() == "requirements.txt"


def test_node_runner_artifact():
    r = NodeRunner()
    assert r.resolve_artifact_path() == "package.json"
