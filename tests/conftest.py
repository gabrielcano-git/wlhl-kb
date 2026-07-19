from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def wlhl_db(tmp_path):
    target = tmp_path / "wlhl.sqlite"
    shutil.copy2(ROOT / "database-init.sqlite", target)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("DELETE FROM prompt_presets")
    connection.execute("DELETE FROM prompt_history")
    connection.commit()
    yield connection
    connection.close()
