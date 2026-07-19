"""Transactional episode and related-content operations.

Functions accept a DB-API connection so they can be tested with isolated SQLite
databases while the application uses the same code against Turso.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime

from unified_search import refresh_episode as refresh_unified_search_episode


ENRICHMENT_LISTS = [
    "secondary_nick_frameworks",
    "incidental_nick_concepts",
    "simple_tags",
    "emotional_themes",
    "target_audience",
    "weight_loss_stage",
    "topic_tags",
    "search_queries",
    "hidden_concepts",
    "myths_debunked",
    "key_takeaways",
    "caller_questions",
]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def split_manual(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def load_enrichment(connection, episode_id: int) -> dict:
    row = connection.execute("SELECT * FROM episode_enrichment WHERE episode_id=?", (episode_id,)).fetchone()
    if not row:
        return {}
    data = dict(row)
    for field in ENRICHMENT_LISTS:
        try:
            data[field] = json.loads(data.get(field) or "[]")
        except (TypeError, json.JSONDecodeError):
            data[field] = []
    return data


def _refresh_legacy_episode_search(connection, episode_id: int) -> None:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_search'"
    ).fetchone():
        return
    row = connection.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
    connection.execute("DELETE FROM episode_search WHERE episode_db_id=?", (episode_id,))
    if not row:
        return
    terms: dict[str, list[str]] = {}
    for item in connection.execute("SELECT kind,value FROM episode_terms WHERE episode_id=?", (episode_id,)):
        terms.setdefault(item["kind"], []).append(item["value"])
    topics = " ".join(
        item[0]
        for item in connection.execute(
            "SELECT t.name FROM episode_topics et JOIN topics t ON t.id=et.topic_id "
            "WHERE et.episode_id=? ORDER BY et.is_primary DESC,t.name",
            (episode_id,),
        )
    )
    quotes = " ".join(
        item[0] for item in connection.execute("SELECT quote FROM quotes WHERE episode_id=?", (episode_id,))
    )
    connection.execute(
        "INSERT INTO episode_search VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            episode_id,
            row["episode_title"],
            " ".join([row["short_summary"] or "", row["detailed_summary"] or ""]),
            " ".join(terms.get("key_takeaway", [])),
            row["nicks_main_advice"] or "",
            row["caller_problem"] or "",
            row["transcript"] or "",
            " ".join(
                terms.get("keyword", []) + terms.get("search_term", []) + terms.get("hidden_concept", [])
            ),
            quotes,
            topics,
            row["guest_caller_name"] or "",
        ),
    )


def _refresh_enrichment_search(connection, episode_id: int) -> None:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='enrichment_search'"
    ).fetchone():
        return
    row = connection.execute(
        "SELECT e.id,e.episode_title,e.transcript,x.* FROM episodes e "
        "JOIN episode_enrichment x ON x.episode_id=e.id WHERE e.id=?",
        (episode_id,),
    ).fetchone()
    connection.execute("DELETE FROM enrichment_search WHERE episode_db_id=?", (episode_id,))
    if not row:
        return

    def unpack(field: str) -> str:
        try:
            return " ".join(json.loads(row[field] or "[]"))
        except (TypeError, json.JSONDecodeError):
            return ""

    simple = unpack("simple_tags")
    topic = " ".join([row["main_category"] or "", unpack("topic_tags")])
    semantic = " ".join(
        [
            row["central_question"] or "",
            row["central_struggle"] or "",
            row["core_coaching_theme"] or "",
            row["primary_nick_framework"] or "",
            *(unpack(field) for field in ENRICHMENT_LISTS),
        ]
    )
    connection.execute(
        "INSERT INTO enrichment_search VALUES(?,?,?,?,?,?)",
        (episode_id, row["episode_title"], simple, topic, semantic, row["transcript"] or ""),
    )


def _refresh_all_indexes(connection, episode_id: int) -> None:
    _refresh_legacy_episode_search(connection, episode_id)
    _refresh_enrichment_search(connection, episode_id)
    refresh_unified_search_episode(connection, episode_id, commit=False)


def _commit_or_rollback(connection, operation):
    try:
        result = operation()
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


def create_episode(connection, values: dict) -> int:
    """Create an episode and all derived search records atomically."""

    def operation() -> int:
        number = int(values["episode_number"])
        external_id = f"EP-{number:03d}"
        if connection.execute("SELECT 1 FROM episodes WHERE episode_number=?", (number,)).fetchone():
            raise ValueError(f"{external_id} already exists")
        filename = values["transcript_filename"]
        if connection.execute("SELECT 1 FROM episodes WHERE transcript_filename=?", (filename,)).fetchone():
            raise ValueError("That transcript filename already exists")
        transcript = values["transcript"]
        now = datetime.now().isoformat(timespec="seconds")
        columns = [
            "episode_id", "episode_number", "episode_title", "publish_date", "youtube_url",
            "transcript_filename", "relative_transcript_path", "episode_type", "guest_caller_name",
            "main_topic", "main_category", "short_summary", "detailed_summary", "nicks_main_advice",
            "caller_problem", "resolution", "weight_loss_stage", "cta_recommendation", "transcript_status",
            "review_notes", "central_struggle", "core_coaching_theme", "success_story", "transcript",
            "source_hash", "source_mtime", "processed_at",
        ]
        row = [
            external_id, number, values["episode_title"], str(values["publish_date"]), values["youtube_url"],
            filename, f"transcripts/{filename}", values["episode_type"], values.get("caller", ""),
            values.get("main_category", ""), values.get("main_category", ""), "", "", "", "", "", "", "",
            "Manual Entry", json.dumps(["Created manually in the WLHL app"]), values.get("central_struggle", ""),
            values.get("core_coaching_theme", ""), int(values.get("success_story", False)), transcript,
            hashlib.sha256(transcript.encode()).hexdigest(), 0, now,
        ]
        cursor = connection.execute(
            f"INSERT INTO episodes({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", row
        )
        episode_id = getattr(cursor, "lastrowid", None)
        if not episode_id:
            episode_id = connection.execute("SELECT id FROM episodes WHERE episode_number=?", (number,)).fetchone()[0]
        payload = {
            field: json.dumps(split_manual(values.get(field, "")), ensure_ascii=False)
            for field in ENRICHMENT_LISTS
        }
        scalar_fields = [
            "episode_id", "source_episode_number", "source_episode_title", "episode_type", "main_category",
            "central_question", "central_struggle", "core_coaching_theme", "primary_nick_framework",
        ]
        enrichment_columns = [*scalar_fields, *ENRICHMENT_LISTS, "source_filename", "source_hash", "imported_at"]
        enrichment_row = [
            episode_id, external_id, values["episode_title"], values["episode_type"], values.get("main_category", ""),
            values.get("central_question", ""), values.get("central_struggle", ""),
            values.get("core_coaching_theme", ""), values.get("primary_nick_framework", ""),
            *(payload[field] for field in ENRICHMENT_LISTS), "Manual app entry",
            hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest(), now,
        ]
        connection.execute(
            f"INSERT INTO episode_enrichment({','.join(enrichment_columns)}) "
            f"VALUES({','.join('?' for _ in enrichment_columns)})",
            enrichment_row,
        )
        for field in ENRICHMENT_LISTS:
            for item in json.loads(payload[field]):
                connection.execute(
                    "INSERT OR IGNORE INTO enrichment_values(episode_id,kind,value,normalized_value) VALUES(?,?,?,?)",
                    (episode_id, field, item, normalize(item)),
                )
        _refresh_all_indexes(connection, episode_id)
        return int(episode_id)

    return _commit_or_rollback(connection, operation)


def update_episode(connection, episode_id: int, values: dict) -> None:
    """Update editable episode fields and derived records atomically."""

    def operation() -> None:
        existing = load_enrichment(connection, episode_id)
        parsed = {field: split_manual(values.get(field, "")) for field in ENRICHMENT_LISTS}
        connection.execute(
            """UPDATE episodes SET episode_title=?,publish_date=?,youtube_url=?,episode_type=?,
            guest_caller_name=?,main_topic=?,main_category=?,nicks_main_advice=?,caller_problem=?,resolution=?,
            weight_loss_stage=?,cta_recommendation=?,central_struggle=?,core_coaching_theme=?,success_story=? WHERE id=?""",
            (
                values["episode_title"].strip(), str(values["publish_date"]), values["youtube_url"].strip(),
                values["episode_type"].strip(), values["caller"].strip(), values["main_category"].strip(),
                values["main_category"].strip(), values["nicks_main_advice"].strip(), values["caller_problem"].strip(),
                values["resolution"].strip(), "; ".join(parsed["weight_loss_stage"]),
                values["cta_recommendation"].strip(), values["central_struggle"].strip(),
                values["core_coaching_theme"].strip(), int(values["success_story"]), episode_id,
            ),
        )
        scalar = {
            "source_episode_title": values["episode_title"].strip(),
            "episode_type": values["episode_type"].strip(),
            "main_category": values["main_category"].strip(),
            "central_question": values["central_question"].strip(),
            "central_struggle": values["central_struggle"].strip(),
            "core_coaching_theme": values["core_coaching_theme"].strip(),
            "primary_nick_framework": values["primary_nick_framework"].strip(),
        }
        if existing:
            fields = [*scalar, *ENRICHMENT_LISTS]
            connection.execute(
                f"UPDATE episode_enrichment SET {','.join(f'{field}=?' for field in fields)} WHERE episode_id=?",
                [*scalar.values(), *(json.dumps(parsed[field], ensure_ascii=False) for field in ENRICHMENT_LISTS), episode_id],
            )
        else:
            episode = connection.execute("SELECT episode_id FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if not episode:
                raise ValueError("Episode not found")
            columns = ["episode_id", "source_episode_number", *scalar, *ENRICHMENT_LISTS, "source_filename", "source_hash", "imported_at"]
            payload = [
                episode_id, episode["episode_id"], *scalar.values(),
                *(json.dumps(parsed[field], ensure_ascii=False) for field in ENRICHMENT_LISTS),
                "Manual app edit", "", datetime.now().isoformat(timespec="seconds"),
            ]
            connection.execute(
                f"INSERT INTO episode_enrichment({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", payload
            )
        connection.execute("DELETE FROM enrichment_values WHERE episode_id=?", (episode_id,))
        for field, items in parsed.items():
            for item in items:
                connection.execute(
                    "INSERT OR IGNORE INTO enrichment_values(episode_id,kind,value,normalized_value) VALUES(?,?,?,?)",
                    (episode_id, field, item, normalize(item)),
                )
        _refresh_all_indexes(connection, episode_id)

    _commit_or_rollback(connection, operation)


def delete_episode(connection, episode_id: int) -> str:
    """Delete an episode and all related records atomically."""

    def operation() -> str:
        row = connection.execute("SELECT episode_id,episode_title FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not row:
            return "Episode"
        label = f"{row['episode_id']} · {row['episode_title']}"
        for table in [
            "quotes", "email_ideas", "short_hooks", "processing_issues", "enrichment_values", "episode_terms",
            "episode_topics", "episode_enrichment",
        ]:
            connection.execute(f"DELETE FROM {table} WHERE episode_id=?", (episode_id,))
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_search'").fetchone():
            connection.execute("DELETE FROM episode_search WHERE episode_db_id=?", (episode_id,))
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='enrichment_search'").fetchone():
            connection.execute("DELETE FROM enrichment_search WHERE episode_db_id=?", (episode_id,))
        connection.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
        refresh_unified_search_episode(connection, episode_id, commit=False)
        return label

    return _commit_or_rollback(connection, operation)


def save_related_content(connection, table: str, episode_id: int, values: dict, item_id: int | None = None) -> None:
    """Insert or update a quote, email idea, or short hook and refresh search atomically."""
    columns_by_table = {
        "quotes": ("quote", "speaker", "topic"),
        "email_ideas": ("topic", "idea", "suggested_subject", "cta"),
        "short_hooks": ("topic", "hook", "exact_or_adapted"),
    }
    if table not in columns_by_table:
        raise ValueError("Unsupported related-content table")
    columns = columns_by_table[table]

    def operation() -> None:
        payload = [values.get(column, "").strip() for column in columns]
        if item_id is None:
            connection.execute(
                f"INSERT INTO {table}(episode_id,{','.join(columns)}) VALUES({','.join('?' for _ in range(len(columns) + 1))})",
                [episode_id, *payload],
            )
        else:
            connection.execute(
                f"UPDATE {table} SET {','.join(f'{column}=?' for column in columns)} WHERE id=? AND episode_id=?",
                [*payload, item_id, episode_id],
            )
        _refresh_all_indexes(connection, episode_id)

    _commit_or_rollback(connection, operation)


def delete_related_content(connection, table: str, episode_id: int, item_id: int) -> None:
    if table not in {"quotes", "email_ideas", "short_hooks"}:
        raise ValueError("Unsupported related-content table")

    def operation() -> None:
        connection.execute(f"DELETE FROM {table} WHERE id=? AND episode_id=?", (item_id, episode_id))
        _refresh_all_indexes(connection, episode_id)

    _commit_or_rollback(connection, operation)
