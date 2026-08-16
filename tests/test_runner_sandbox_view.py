from __future__ import annotations

from scriptdeck.runner.python_runner import PythonRunner
from scriptdeck.runner.node_runner import NodeRunner


def test_python_runner_sandbox_view_includes_python():
    v = PythonRunner().sandbox_view()
    jails = [bm.jail for bm in v.binds]
    assert "/usr/bin/python3" in jails


def test_python_runner_sandbox_view_readonly():
    v = PythonRunner().sandbox_view()
    assert all(bm.readonly for bm in v.binds)


def test_node_runner_sandbox_view_includes_node():
    v = NodeRunner().sandbox_view()
    jails = [bm.jail for bm in v.binds]
    assert "/usr/bin/node" in jails
