"""Portable SQLite database layer for the WLHL Knowledge Base."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "database.sqlite"
LOCAL_TRANSCRIPTS = PROJECT_ROOT / "transcripts"
SIBLING_TRANSCRIPTS = PROJECT_ROOT.parent / "YT Transcripts"

FILENAME_RE = re.compile(r"^(EP-(\d{3}))\b.*\.txt$", re.IGNORECASE)
HEADER_RE = re.compile(r"^(EP-\d{3})\s*\|\s*(.*?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*$")
URL_RE = re.compile(r"^https?://(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})")
SEPARATOR_RE = re.compile(r"^-{3,}\s*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def transcript_directory() -> Path:
    if LOCAL_TRANSCRIPTS.is_dir() and any(LOCAL_TRANSCRIPTS.glob("*.txt")):
        return LOCAL_TRANSCRIPTS
    if SIBLING_TRANSCRIPTS.is_dir():
        return SIBLING_TRANSCRIPTS
    raise FileNotFoundError(
        "No transcripts found. Place the canonical .txt files in 'transcripts/' "
        "or keep 'YT Transcripts' beside the Knowledge Base folder."
    )


def portable_path(path: Path) -> str:
    return Path(os.path.relpath(path, PROJECT_ROOT)).as_posix()


def resolve_portable_path(value: str) -> Path:
    return PROJECT_ROOT.joinpath(*PurePosixPath(value).parts).resolve()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_transcript(path: Path) -> dict:
    filename_match = FILENAME_RE.match(path.name)
    if not filename_match:
        raise ValueError("Filename does not begin with EP-XXX")
    episode_label = filename_match.group(1).upper()
    episode_number = int(filename_match.group(2))
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    title = path.stem[len(episode_label):].lstrip(" -")
    publish_date = ""
    header_episode = ""
    issues = []
    if lines:
        match = HEADER_RE.match(lines[0].strip())
        if match:
            header_episode, title, publish_date = match.groups()
            if header_episode != episode_label:
                issues.append(("Header episode mismatch", "Review", f"Filename says {episode_label}; header says {header_episode}. Canonical filename retained."))
        else:
            issues.append(("Header parsing error", "Critical", "First line does not match EP-XXX | Title | YYYY-MM-DD."))
    else:
        issues.append(("Empty transcript", "Critical", "The file is empty."))

    youtube_url = next((line.strip().replace("https://www.youtube.com/", "https://youtube.com/")
                        for line in lines[1:6] if URL_RE.match(line.strip())), "")
    if not youtube_url:
        issues.append(("URL parsing error", "Critical", "YouTube URL not found near the header."))

    separator = next((i for i, line in enumerate(lines) if SEPARATOR_RE.match(line.strip())), None)
    if separator is None:
        transcript = "\n".join(lines[2:]).strip()
        issues.append(("Missing separator", "Critical", "Transcript separator was not found."))
    else:
        transcript = "\n".join(lines[separator + 1:]).strip()
    status = "Complete"
    if not transcript:
        status = "Empty"
    elif len(transcript) < 500:
        status = "Potentially Incomplete"
        issues.append(("Potentially incomplete", "Review", f"Only {len(transcript)} transcript characters found."))
    return {
        "episode_number": episode_number,
        "episode_label": episode_label,
        "title": title.strip(),
        "publish_date": publish_date,
        "youtube_url": youtube_url,
        "transcript_filename": path.name,
        "relative_transcript_path": portable_path(path),
        "transcript": transcript,
        "transcript_status": status,
        "file_hash": file_hash(path),
        "issues": issues,
    }


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY,
            episode_number INTEGER NOT NULL,
            episode_label TEXT NOT NULL,
            title TEXT NOT NULL,
            publish_date TEXT,
            youtube_url TEXT,
            transcript_filename TEXT NOT NULL UNIQUE,
            relative_transcript_path TEXT NOT NULL,
            transcript TEXT NOT NULL,
            episode_type TEXT NOT NULL DEFAULT 'Unknown',
            guest_caller_name TEXT DEFAULT '',
            main_topic TEXT DEFAULT '',
            semantic_keywords TEXT DEFAULT '[]',
            short_summary TEXT DEFAULT '',
            detailed_summary TEXT DEFAULT '',
            key_takeaways TEXT DEFAULT '[]',
            nicks_advice TEXT DEFAULT '',
            caller_problem TEXT DEFAULT '',
            resolution TEXT DEFAULT '',
            relevant_audience TEXT DEFAULT '[]',
            emotional_themes TEXT DEFAULT '[]',
            weight_loss_stage TEXT DEFAULT '',
            cta_recommendation TEXT DEFAULT '',
            is_success_story INTEGER NOT NULL DEFAULT 0,
            transcript_status TEXT NOT NULL,
            review_notes TEXT DEFAULT 'Semantic enrichment pending AI or human review.',
            file_hash TEXT NOT NULL,
            added_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_episode_number ON episodes(episode_number);
        CREATE INDEX IF NOT EXISTS idx_episode_date ON episodes(publish_date);
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS episode_topics (
            episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            is_main INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (episode_id, topic_id)
        );
        CREATE TABLE IF NOT EXISTS callers (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS episode_callers (
            episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
            caller_id INTEGER NOT NULL REFERENCES callers(id) ON DELETE CASCADE,
            appearance_notes TEXT DEFAULT '',
            PRIMARY KEY (episode_id, caller_id)
        );
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY, episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
            quote TEXT NOT NULL, speaker TEXT DEFAULT '', topic_id INTEGER REFERENCES topics(id), is_exact INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS email_ideas (
            id INTEGER PRIMARY KEY, episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
            topic_id INTEGER REFERENCES topics(id), idea TEXT NOT NULL, subject_line TEXT DEFAULT '', cta TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS short_hooks (
            id INTEGER PRIMARY KEY, episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
            topic_id INTEGER REFERENCES topics(id), hook TEXT NOT NULL, source_type TEXT DEFAULT 'Adapted'
        );
        CREATE TABLE IF NOT EXISTS processing_issues (
            id INTEGER PRIMARY KEY, episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
            episode_label TEXT, transcript_filename TEXT, issue_type TEXT, severity TEXT, details TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
            episode_id UNINDEXED, title, transcript, topics, keywords, summaries, quotes, callers,
            tokenize='porter unicode61'
        );
    """)
    db.commit()


def refresh_search_index(db: sqlite3.Connection, episode_id: int | None = None) -> None:
    where = "WHERE e.id = ?" if episode_id is not None else ""
    params = (episode_id,) if episode_id is not None else ()
    if episode_id is None:
        db.execute("DELETE FROM episodes_fts")
    else:
        db.execute("DELETE FROM episodes_fts WHERE episode_id = ?", (episode_id,))
    rows = db.execute(f"""
        SELECT e.*,
          COALESCE((SELECT group_concat(t.name, ' ') FROM episode_topics et JOIN topics t ON t.id=et.topic_id WHERE et.episode_id=e.id), '') AS topic_text,
          COALESCE((SELECT group_concat(q.quote, ' ') FROM quotes q WHERE q.episode_id=e.id), '') AS quote_text,
          COALESCE((SELECT group_concat(c.name, ' ') FROM episode_callers ec JOIN callers c ON c.id=ec.caller_id WHERE ec.episode_id=e.id), '') AS caller_text
        FROM episodes e {where}
    """, params).fetchall()
    for row in rows:
        summaries = " ".join(filter(None, [row["short_summary"], row["detailed_summary"], row["nicks_advice"], row["caller_problem"], row["resolution"]]))
        db.execute("INSERT INTO episodes_fts VALUES (?,?,?,?,?,?,?,?)", (
            row["id"], row["title"], row["transcript"], row["topic_text"], row["semantic_keywords"],
            summaries, row["quote_text"], " ".join(filter(None, [row["guest_caller_name"], row["caller_text"]])),
        ))
    db.commit()


def update_database() -> dict:
    source = transcript_directory()
    files = sorted(source.glob("*.txt"), key=lambda p: (int(FILENAME_RE.match(p.name).group(2)) if FILENAME_RE.match(p.name) else 10**9, p.name))
    db = connect()
    create_schema(db)
    existing = {row["transcript_filename"]: row for row in db.execute("SELECT * FROM episodes")}
    new_count = changed_count = unchanged_count = failed_count = 0
    now = utc_now()
    for path in files:
        try:
            parsed = parse_transcript(path)
            old = existing.get(path.name)
            if old and old["file_hash"] == parsed["file_hash"]:
                unchanged_count += 1
                continue
            if old:
                db.execute("""UPDATE episodes SET episode_number=?, episode_label=?, title=?, publish_date=?, youtube_url=?,
                    relative_transcript_path=?, transcript=?, transcript_status=?, file_hash=?, updated_at=? WHERE id=?""",
                    (parsed["episode_number"], parsed["episode_label"], parsed["title"], parsed["publish_date"], parsed["youtube_url"],
                     parsed["relative_transcript_path"], parsed["transcript"], parsed["transcript_status"], parsed["file_hash"], now, old["id"]))
                episode_id = old["id"]
                changed_count += 1
            else:
                cursor = db.execute("""INSERT INTO episodes
                    (episode_number,episode_label,title,publish_date,youtube_url,transcript_filename,relative_transcript_path,
                     transcript,transcript_status,file_hash,added_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (parsed["episode_number"], parsed["episode_label"], parsed["title"], parsed["publish_date"], parsed["youtube_url"],
                     parsed["transcript_filename"], parsed["relative_transcript_path"], parsed["transcript"], parsed["transcript_status"],
                     parsed["file_hash"], now, now))
                episode_id = cursor.lastrowid
                new_count += 1
            db.execute("DELETE FROM processing_issues WHERE episode_id=?", (episode_id,))
            for issue_type, severity, details in parsed["issues"]:
                db.execute("""INSERT INTO processing_issues
                    (episode_id,episode_label,transcript_filename,issue_type,severity,details,created_at) VALUES (?,?,?,?,?,?,?)""",
                    (episode_id, parsed["episode_label"], path.name, issue_type, severity, details, now))
            db.commit()
            refresh_search_index(db, episode_id)
        except Exception as exc:
            failed_count += 1
            db.execute("""INSERT INTO processing_issues
                (episode_label,transcript_filename,issue_type,severity,details,created_at) VALUES (?,?,?,?,?,?)""",
                ("", path.name, "Processing error", "Critical", str(exc), now))
            db.commit()

    refresh_search_index(db)
    db.execute("INSERT OR REPLACE INTO app_meta VALUES ('last_update', ?)", (now,))
    db.execute("INSERT OR REPLACE INTO app_meta VALUES ('transcript_source', ?)", (portable_path(source),))
    db.commit()
    total = db.execute("SELECT count(*) FROM episodes").fetchone()[0]
    db.close()
    return {"source": portable_path(source), "files_found": len(files), "total_episodes": total,
            "new": new_count, "modified": changed_count, "unchanged": unchanged_count, "failures": failed_count}
