from __future__ import annotations

import unified_search
from db_compat import execute_script, is_fts_unavailable
from unified_search import ensure_index, rebuild_index, refresh_episode, search, source_signature


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


def test_source_signature_is_stable_and_detects_content_edits(wlhl_db):
    signature = source_signature(wlhl_db)
    assert source_signature(wlhl_db) == signature
    episode_id = wlhl_db.execute("SELECT MIN(id) FROM episodes").fetchone()[0]
    wlhl_db.execute("UPDATE episodes SET episode_title = episode_title || ' edited' WHERE id=?", (episode_id,))
    assert source_signature(wlhl_db) != signature


def test_refresh_episode_updates_one_document_without_a_full_rebuild(wlhl_db, monkeypatch):
    ensure_index(wlhl_db)
    episode_id = wlhl_db.execute("SELECT MIN(id) FROM episodes").fetchone()[0]
    # Prove the single-episode refresh never falls back to rebuilding everything.
    monkeypatch.setattr(
        unified_search, "rebuild_index", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("full rebuild"))
    )
    wlhl_db.execute("UPDATE episodes SET episode_title='Refreshed Incrementally' WHERE id=?", (episode_id,))
    refresh_episode(wlhl_db, episode_id)
    title = wlhl_db.execute("SELECT title FROM unified_search_documents WHERE episode_db_id=?", (episode_id,)).fetchone()[0]
    assert "Refreshed Incrementally" in title
    assert any(item["episode_db_id"] == episode_id for item in search(wlhl_db, "Refreshed Incrementally"))


def test_ensure_index_takes_fast_path_after_incremental_refresh(wlhl_db, monkeypatch):
    ensure_index(wlhl_db)
    episode_id = wlhl_db.execute("SELECT MIN(id) FROM episodes").fetchone()[0]
    wlhl_db.execute("UPDATE episodes SET episode_title='Signature Kept Current' WHERE id=?", (episode_id,))
    refresh_episode(wlhl_db, episode_id)
    calls = {"rebuilds": 0}
    original = unified_search.rebuild_index
    monkeypatch.setattr(
        unified_search, "rebuild_index", lambda *a, **k: (calls.__setitem__("rebuilds", calls["rebuilds"] + 1), original(*a, **k))[1]
    )
    assert ensure_index(wlhl_db) is False
    assert calls["rebuilds"] == 0


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
