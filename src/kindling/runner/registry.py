from __future__ import annotations

from kindling.runner.bash_runner import BashRunner
from kindling.runner.node_runner import NodeRunner
from kindling.runner.protocol import LanguageRunner
from kindling.runner.python_runner import PythonRunner

RUNNERS: dict[str, LanguageRunner] = {
    "python": PythonRunner(),
    "node": NodeRunner(),
    "bash": BashRunner(),
}


def get_runner(language: str) -> LanguageRunner:
    return RUNNERS[language]
