import os

import pytest

from database_connection import connect, validate_schema


@pytest.mark.turso
def test_real_turso_contains_expected_episode_count_read_only():
    if os.getenv("RUN_TURSO_TEST") != "1":
        pytest.skip("Set RUN_TURSO_TEST=1 to enable the real read-only Turso check")
    connection = connect()
    try:
        assert validate_schema(connection) == 127
        row = connection.execute("SELECT episode_id,episode_title FROM episodes ORDER BY id LIMIT 1").fetchone()
        assert row[0] and row[1]
    finally:
        connection.close()
