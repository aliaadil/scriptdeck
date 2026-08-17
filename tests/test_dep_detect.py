from kindling.services.dep_detect import detect_node_deps, detect_python_deps


def test_python_basic_imports():
    src = """
import requests
from pandas import DataFrame
import os
from .local import thing
"""
    assert detect_python_deps(src) == ["pandas", "requests"]


def test_python_syntax_error_returns_empty():
    assert detect_python_deps("def broken(:") == []


def test_node_requires_and_imports():
    src = """
const a = require('axios');
import { foo } from 'lodash';
import x from './local';
const path = require('path');
"""
    assert detect_node_deps(src) == ["axios", "lodash"]


def test_node_scoped_packages():
    src = "import { foo } from '@scope/pkg';"
    assert detect_node_deps(src) == ["@scope/pkg"]


def test_node_node_prefix():
    src = "const fs = require('node:fs');"
    assert detect_node_deps(src) == []
