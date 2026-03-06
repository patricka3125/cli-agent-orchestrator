"""Shared fixtures for provider integration tests."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def cleanup_orphaned_test_dirs():
    """Remove any orphaned ~/.cao_test_tmp_* directories left by previous crashed runs.

    Temp dirs created by the ``home_tmp_path`` fixture can be orphaned when a test
    process is killed via SIGKILL, OOM, etc. before the fixture teardown runs.
    This session-scoped autouse fixture sweeps them away at the start of every
    test session so stale directories do not accumulate under $HOME.
    """
    home = Path.home()
    pattern = ".cao_test_tmp_*"

    # Pre-session cleanup: remove dirs left by previous crashed runs.
    for orphan in home.glob(pattern):
        if orphan.is_dir():
            shutil.rmtree(orphan, ignore_errors=True)

    yield

    # Post-session cleanup: catch any dirs left by a crash in this session.
    for orphan in home.glob(pattern):
        if orphan.is_dir():
            shutil.rmtree(orphan, ignore_errors=True)
