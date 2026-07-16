#!/usr/bin/env python3
"""Import reviewed WLHL episode enrichment from CSV without changing transcripts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database.sqlite"
IMPORTS = ROOT / "imports"
REPORT = ROOT / "database" / "enrichment_import_report.json"

COLUMN_MAP = {
    "Episode Type": "episode_type", "Main Category": "main_category",
    "Central Question": "central_question", "Central Struggle": "central_struggle",
    "Core Coaching Theme": "core_coaching_theme", "Primary Nick Framework": "primary_nick_framework",
    "Secondary Nick Frameworks": "secondary_nick_frameworks", "Incidental Nick Concepts": "incidental_nick_concepts",
    "Simple Tags": "simple_tags", "Emotional Themes": "emotional_themes", "Target Audience": "target_audience",
    "Weight Loss Stage": "weight_loss_stage", "Topic Tags": "topic_tags", "Search Queries": "search_queries",
    "Hidden Concepts": "hidden_concepts", "Myths Debunked": "myths_debunked", "Key Takeaways": "key_takeaways",
    "Caller's Questions (if episode is call-in)": "caller_questions",
}
LIST_FIELDS = {
    "secondary_nick_frameworks", "incidental_nick_concepts", "simple_tags", "emotional_themes",
    "target_audience", "weight_loss_stage", "topic_tags", "search_queries", "hidden_concepts",
    "myths_debunked", "key_takeaways", "caller_questions",
}

COMMA_SEPARATED_FIELDS = {
    "secondary_nick_frameworks", "incidental_nick_concepts", "simple_tags", "emotional_themes",
    "target_audience", "weight_loss_stage", "topic_tags", "search_queries", "hidden_concepts",
}

def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def episode_number(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None

def split_values(value: str, field: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    separator = ";" if ";" in value else ("," if field in COMMA_SEPARATED_FIELDS else None)
    return [part.strip() for part in value.split(separator) if part.strip()] if separator else [value]

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS episode_enrichment (
      episode_id INTEGER PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
      source_episode_number TEXT, source_episode_title TEXT, episode_type TEXT, main_category TEXT,
      central_question TEXT, central_struggle TEXT, core_coaching_theme TEXT, primary_nick_framework TEXT,
      secondary_nick_frameworks TEXT, incidental_nick_concepts TEXT, simple_tags TEXT, emotional_themes TEXT,
      target_audience TEXT, weight_loss_stage TEXT, topic_tags TEXT, search_queries TEXT, hidden_concepts TEXT,
      myths_debunked TEXT, key_takeaways TEXT, caller_questions TEXT, source_filename TEXT, source_hash TEXT, imported_at TEXT
    );
    CREATE TABLE IF NOT EXISTS enrichment_values (
      episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
      kind TEXT NOT NULL, value TEXT NOT NULL, normalized_value TEXT NOT NULL,
      PRIMARY KEY(episode_id,kind,value)
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS enrichment_search USING fts5(
      episode_db_id UNINDEXED, title, simple_tags, topic_category, semantic_context, transcript,
      tokenize='porter unicode61'
    );
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(episode_enrichment)")}
    if "caller_questions" not in columns:
        conn.execute("ALTER TABLE episode_enrichment ADD COLUMN caller_questions TEXT")

def main() -> int:
    parser = argparse.ArgumentParser(description="Import WLHL semantic metadata from CSV")
    parser.add_argument("csv_file", nargs="?", default=str(IMPORTS / "WLHL_episode_enrichment.csv"))
    args = parser.parse_args()
    source = Path(args.csv_file).expanduser().resolve()
    if not source.exists(): raise SystemExit(f"CSV not found: {source}")
    raw = source.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    with source.open(encoding="utf-8-sig", newline="") as handle: rows = list(csv.DictReader(handle))
    required = {"Episode Number", "Episode Title", *COLUMN_MAP.keys()}
    missing_headers = sorted(required - set(rows[0] if rows else []))
    if missing_headers: raise SystemExit("Missing columns: " + ", ".join(missing_headers))

    deduped, duplicate_rows = {}, []
    for row in rows:
        key = (episode_number(row["Episode Number"]), normalize(row["Episode Title"]))
        if key in deduped:
            if row != deduped[key]: raise SystemExit(f"Conflicting duplicate spreadsheet rows for {row['Episode Number']}")
            duplicate_rows.append(row["Episode Number"])
        else: deduped[key] = row

    backup_dir = ROOT / "database" / "backups"; backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(DB, backup_dir / f"database-before-enrichment-{stamp}.sqlite")

    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON"); init_schema(conn)
    imported, unmatched, ambiguous, title_warnings, alignment_corrections = [], [], [], [], []
    for (number, normalized_title), row in deduped.items():
        candidates = conn.execute("SELECT id,episode_title,transcript FROM episodes WHERE episode_number=?", (number,)).fetchall()
        if not candidates:
            unmatched.append(row["Episode Number"]); continue
        if len(candidates) > 1:
            exact = [candidate for candidate in candidates if normalize(candidate["episode_title"]) == normalized_title]
            if len(exact) != 1:
                ambiguous.append(row["Episode Number"]); continue
            episode = exact[0]
        else:
            episode = candidates[0]
            if normalize(episode["episode_title"]) != normalized_title:
                title_warnings.append({"episode": row["Episode Number"], "spreadsheet": row["Episode Title"], "database": episode["episode_title"]})

        stage_text = (row.get("Weight Loss Stage") or "").strip()
        if len(stage_text) > 80 or normalize(stage_text).startswith(("people ", "chronic ")):
            corrected = dict(row)
            corrected["Simple Tags"] = row.get("Emotional Themes", "")
            corrected["Emotional Themes"] = row.get("Target Audience", "")
            corrected["Target Audience"] = row.get("Weight Loss Stage", "")
            corrected["Weight Loss Stage"] = row.get("Simple Tags", "")
            row = corrected
            alignment_corrections.append({"episode": row["Episode Number"], "reason": "Realigned shifted Simple Tags, Emotional Themes, Target Audience, and Weight Loss Stage"})

        payload = {}
        for source_column, db_column in COLUMN_MAP.items():
            value = (row.get(source_column) or "").strip()
            payload[db_column] = json.dumps(split_values(value, db_column), ensure_ascii=False) if db_column in LIST_FIELDS else value
        columns = ["episode_id", "source_episode_number", "source_episode_title", *COLUMN_MAP.values(), "source_filename", "source_hash", "imported_at"]
        values = [episode["id"], row["Episode Number"], row["Episode Title"], *[payload[x] for x in COLUMN_MAP.values()], source.name, digest, datetime.now().isoformat(timespec="seconds")]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{column}=excluded.{column}" for column in columns[1:])
        conn.execute(f"INSERT INTO episode_enrichment({','.join(columns)}) VALUES({placeholders}) ON CONFLICT(episode_id) DO UPDATE SET {updates}", values)
        conn.execute("DELETE FROM enrichment_values WHERE episode_id=?", (episode["id"],))
        for field in LIST_FIELDS:
            for item in json.loads(payload[field] or "[]"):
                conn.execute("INSERT OR IGNORE INTO enrichment_values VALUES(?,?,?,?)", (episode["id"], field, item, normalize(item)))
        imported.append(row["Episode Number"])

    conn.execute("DELETE FROM enrichment_search")
    for episode in conn.execute("SELECT e.id,e.episode_title,e.transcript,x.* FROM episodes e JOIN episode_enrichment x ON x.episode_id=e.id"):
        unpack = lambda field: " ".join(json.loads(episode[field] or "[]"))
        simple = unpack("simple_tags")
        topic = " ".join([episode["main_category"] or "", unpack("topic_tags")])
        semantic = " ".join([episode["central_question"] or "", episode["central_struggle"] or "", episode["core_coaching_theme"] or "", episode["primary_nick_framework"] or "", unpack("secondary_nick_frameworks"), unpack("incidental_nick_concepts"), unpack("emotional_themes"), unpack("target_audience"), unpack("weight_loss_stage"), unpack("search_queries"), unpack("hidden_concepts"), unpack("myths_debunked"), unpack("key_takeaways"), unpack("caller_questions")])
        conn.execute("INSERT INTO enrichment_search VALUES(?,?,?,?,?,?)", (episode["id"], episode["episode_title"], simple, topic, semantic, episode["transcript"]))
    conn.commit()
    report = {"source": source.name, "source_sha256": digest, "rows_read": len(rows), "unique_rows": len(deduped), "imported": len(imported), "duplicate_identical_rows_ignored": duplicate_rows, "column_alignment_corrections": alignment_corrections, "unmatched": unmatched, "ambiguous": ambiguous, "title_validation_warnings": title_warnings, "database_integrity": conn.execute("PRAGMA integrity_check").fetchone()[0]}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close(); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if not unmatched and not ambiguous else 2

if __name__ == "__main__": raise SystemExit(main())
