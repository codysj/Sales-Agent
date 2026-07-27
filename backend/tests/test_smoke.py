"""Toolchain smoke checks.

Guards the two ways the scaffold silently breaks: the wrong interpreter is active
(several Python versions are installed on the dev machine) and the ``app`` package
stops being importable from the ``backend/`` working directory.
"""

import sys


def test_interpreter_matches_pinned_minor_version() -> None:
    assert sys.version_info[:2] == (3, 12), f"expected Python 3.12, got {sys.version}"


def test_app_package_imports() -> None:
    import app

    assert app.__doc__, "app package must document what it owns"
