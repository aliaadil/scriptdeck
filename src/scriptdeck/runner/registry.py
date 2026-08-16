from __future__ import annotations

from scriptdeck.runner.node_runner import NodeRunner
from scriptdeck.runner.protocol import LanguageRunner
from scriptdeck.runner.python_runner import PythonRunner

RUNNERS: dict[str, LanguageRunner] = {
    "python": PythonRunner(),
    "node": NodeRunner(),
}


def get_runner(language: str) -> LanguageRunner:
    return RUNNERS[language]
