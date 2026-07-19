from __future__ import annotations

from db_compat import execute_script, is_fts_unavailable
from unified_search import ensure_index, rebuild_index, search


def test_index_rebuild_search_ranking_and_empty_query(wlhl_db):
    count = rebuild_index(wlhl_db)
    assert count == 127
    assert wlhl_db.execute("SELECT COUNT(*) FROM unified_search_documents").fetchone()[0] == 127
    assert search(wlhl_db, "") == []
    results = search(wlhl_db, "maintenance")
    assert results
    assert results == sorted(results, key=lambda item: (-item["score"], item["episode_db_id"]))
    assert all(item["reason"] for item in results)


def test_ensure_index_is_stable_after_rebuild(wlhl_db):
    rebuild_index(wlhl_db)
    assert ensure_index(wlhl_db) is False


def test_execute_script_fallback_and_fts_error_detection(wlhl_db):
    class NoScriptConnection:
        def execute(self, sql, params=()):
            return wlhl_db.execute(sql, params)

    execute_script(NoScriptConnection(), "CREATE TABLE fallback_test(id INTEGER); INSERT INTO fallback_test VALUES(1);")
    assert wlhl_db.execute("SELECT id FROM fallback_test").fetchone()[0] == 1
    assert is_fts_unavailable(RuntimeError("no such module: fts5"))
    assert not is_fts_unavailable(RuntimeError("disk is full"))


def test_index_and_search_fall_back_when_fts_is_unavailable(wlhl_db):
    class NoFtsConnection:
        def execute(self, sql, params=()):
            lowered = sql.lower()
            if "create virtual table" in lowered or "unified_episode_search(unified_episode_search)" in lowered:
                raise RuntimeError("no such module: fts5")
            if "bm25(unified_episode_search" in lowered:
                raise RuntimeError("no such function: bm25")
            return wlhl_db.execute(sql, params)

        def commit(self):
            wlhl_db.commit()

        def rollback(self):
            wlhl_db.rollback()

    connection = NoFtsConnection()
    assert rebuild_index(connection) == 127
    assert search(connection, "maintenance")


def test_complete_portable_index_survives_remote_maintenance_restriction(wlhl_db):
    rebuild_index(wlhl_db)

    class MaintenanceRestrictedConnection:
        def execute(self, sql, params=()):
            if sql.lstrip().lower().startswith(("insert", "delete", "drop", "create", "update")):
                raise RuntimeError("remote maintenance is not supported")
            return wlhl_db.execute(sql, params)

        def rollback(self):
            wlhl_db.rollback()

    connection = MaintenanceRestrictedConnection()
    assert ensure_index(connection) is False
    assert search(connection, "maintenance")
