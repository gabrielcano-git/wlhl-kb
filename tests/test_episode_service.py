from __future__ import annotations

from datetime import date

import pytest

import episode_service
from episode_service import create_episode, delete_episode, update_episode
from unified_search import ensure_index, search


def episode_values(number=900):
    return {
        "episode_number": number,
        "episode_title": "A Durable Test Episode",
        "publish_date": date(2026, 1, 2),
        "youtube_url": "https://youtube.example/test",
        "transcript_filename": f"EP-{number:03d}.txt",
        "episode_type": "Solo",
        "caller": "",
        "main_category": "Consistency",
        "central_question": "How can consistency last?",
        "central_struggle": "All or nothing thinking",
        "core_coaching_theme": "Small actions compound",
        "primary_nick_framework": "Common Sense",
        "simple_tags": "consistency; habits",
        "topic_tags": "long-term weight loss",
        "key_takeaways": "Start small",
        "success_story": False,
        "transcript": "Consistency is built with small actions repeated through real life.",
    }


def test_create_duplicate_update_delete_and_index_sync(wlhl_db):
    ensure_index(wlhl_db)
    episode_id = create_episode(wlhl_db, episode_values())
    assert wlhl_db.execute("SELECT episode_title FROM episodes WHERE id=?", (episode_id,)).fetchone()[0] == "A Durable Test Episode"
    assert any(item["episode_db_id"] == episode_id for item in search(wlhl_db, "small actions"))
    with pytest.raises(ValueError, match="already exists"):
        create_episode(wlhl_db, episode_values())

    edited = episode_values()
    edited.update(
        {
            "episode_title": "An Updated Durable Episode",
            "nicks_main_advice": "Practice on imperfect days",
            "caller_problem": "Restarting",
            "resolution": "Keep going",
            "weight_loss_stage": "Maintenance",
            "cta_recommendation": "Listen",
            "caller_questions": "What happens after a setback?",
        }
    )
    update_episode(wlhl_db, episode_id, edited)
    assert wlhl_db.execute("SELECT episode_title FROM episodes WHERE id=?", (episode_id,)).fetchone()[0].startswith("An Updated")
    assert any(item["episode_db_id"] == episode_id for item in search(wlhl_db, "imperfect days"))

    label = delete_episode(wlhl_db, episode_id)
    assert label.startswith("EP-900")
    assert not wlhl_db.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone()
    assert not wlhl_db.execute("SELECT 1 FROM unified_search_documents WHERE episode_db_id=?", (episode_id,)).fetchone()


def test_create_rolls_back_when_index_refresh_fails(wlhl_db, monkeypatch):
    ensure_index(wlhl_db)
    before = wlhl_db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    monkeypatch.setattr(
        episode_service,
        "refresh_unified_search_episode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("index failed")),
    )
    with pytest.raises(RuntimeError, match="index failed"):
        create_episode(wlhl_db, episode_values(901))
    assert wlhl_db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == before
    assert not wlhl_db.execute("SELECT 1 FROM episodes WHERE episode_number=901").fetchone()
