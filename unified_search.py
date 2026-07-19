"""Unified cross-table search index for the WLHL Knowledge Base."""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata

from db_compat import execute_script, row_field


# The document and FTS tables are derived data.  Keep a separate schema version
# so deployments can safely replace an older derived index stored in Turso.
INDEX_VERSION = "wlhl-unified-search-v2"
INDEX_SCHEMA_VERSION = "2"
INDEX_COLUMNS = [
    "episode_number", "title", "publish_date", "main_category", "central_question",
    "summaries", "main_lesson", "central_struggle", "frameworks", "key_concepts",
    "simple_tags", "semantic_tags", "target_audience", "actionable_takeaways",
    "related_content", "transcript",
]

FIELD_LABELS = {
    "episode_number": "episode number", "title": "episode title", "publish_date": "publish date",
    "main_category": "main category", "central_question": "central question",
    "summaries": "summary", "main_lesson": "main lesson", "central_struggle": "central struggle",
    "frameworks": "framework", "key_concepts": "key concept", "simple_tags": "simple tag",
    "semantic_tags": "semantic tag", "target_audience": "target audience",
    "actionable_takeaways": "actionable takeaway", "related_content": "related episode information",
    "transcript": "transcript",
}

# Priority follows the product requirement. Transcript stays exhaustive but receives the lowest weight.
FIELD_WEIGHTS = {
    "episode_number": 18, "title": 22, "publish_date": 7, "main_category": 15,
    "central_question": 14, "summaries": 14, "main_lesson": 15, "central_struggle": 13,
    "frameworks": 10, "key_concepts": 18, "simple_tags": 15, "semantic_tags": 18,
    "target_audience": 9, "actionable_takeaways": 10, "related_content": 6, "transcript": 2,
}

STOP_WORDS = {
    "a", "about", "all", "an", "and", "any", "are", "did", "do", "episode", "episodes",
    "find", "for", "from", "how", "i", "in", "is", "it", "me", "my", "of", "on", "show",
    "talk", "talked", "talking", "the", "to", "video", "videos", "what", "where", "which", "with",
}

SEMANTIC_EXPANSIONS = {
    "healthy relationship with food": ["food rules", "food guilt", "restriction", "sustainable eating", "all or nothing thinking"],
    "going out to dinner": ["eating out", "restaurant eating", "dining out", "social situations"],
    "dinner with friends": ["restaurant eating", "social pressure", "eating out", "friendships"],
    "maintenance": ["fear of regain", "keeping weight off", "maintenance mindset", "sustainable habits"],
    "plateau": ["weight loss plateau", "scale stopped moving", "scale not moving", "stuck"],
    "motivation": ["consistency", "discipline", "momentum", "reconnecting with your why"],
    "food addiction": ["food noise", "binge eating", "cravings", "loss of control around food"],
    "vacation eating": ["travel eating", "restaurant eating", "holiday eating", "planning ahead"],
    "starting over": ["restarting", "last day 1", "all or nothing thinking", "monday"],
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _json_list(value) -> list[str]:
    try:
        loaded = json.loads(value or "[]")
        return [str(item).strip() for item in loaded if str(item).strip()] if isinstance(loaded, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _unique(values) -> list[str]:
    result=[]; seen=set()
    for value in values:
        value=str(value or "").strip()
        marker=normalize(value)
        if value and marker and marker not in seen:
            seen.add(marker); result.append(value)
    return result


def create_schema(conn, *, commit: bool = True) -> None:
    # Keep the portable document index available even on SQLite builds that do
    # not include the optional FTS5 extension (some hosted Python runtimes).
    required_columns = {"episode_db_id", *INDEX_COLUMNS, "source_map_json"}
    execute_script(conn, """
    CREATE TABLE IF NOT EXISTS unified_search_documents (
      episode_db_id INTEGER PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
      episode_number TEXT, title TEXT, publish_date TEXT, main_category TEXT,
      central_question TEXT, summaries TEXT, main_lesson TEXT, central_struggle TEXT,
      frameworks TEXT, key_concepts TEXT, simple_tags TEXT, semantic_tags TEXT,
      target_audience TEXT, actionable_takeaways TEXT, related_content TEXT,
      transcript TEXT, source_map_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS unified_search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)

    # CREATE TABLE IF NOT EXISTS does not migrate an existing table.  The
    # search index is entirely rebuildable, so replace it when a deployment
    # finds an older layout rather than failing on INSERT with (for example)
    # "table ... has no column named source_map_json".
    document_columns = {
        row_field(row, "name", 1) for row in conn.execute("PRAGMA table_info(unified_search_documents)")
    }
    schema_version = conn.execute(
        "SELECT value FROM unified_search_meta WHERE key='schema_version'"
    ).fetchone()
    if document_columns != required_columns or not schema_version or schema_version[0] != INDEX_SCHEMA_VERSION:
        execute_script(conn, """
        DROP TABLE IF EXISTS unified_episode_search;
        DROP TABLE IF EXISTS unified_search_documents;
        DROP TABLE IF EXISTS unified_search_meta;
        CREATE TABLE unified_search_documents (
          episode_db_id INTEGER PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
          episode_number TEXT, title TEXT, publish_date TEXT, main_category TEXT,
          central_question TEXT, summaries TEXT, main_lesson TEXT, central_struggle TEXT,
          frameworks TEXT, key_concepts TEXT, simple_tags TEXT, semantic_tags TEXT,
          target_audience TEXT, actionable_takeaways TEXT, related_content TEXT,
          transcript TEXT, source_map_json TEXT NOT NULL
        );
        CREATE TABLE unified_search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
    try:
        conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS unified_episode_search USING fts5(
      episode_number, title, publish_date, main_category, central_question,
      summaries, main_lesson, central_struggle, frameworks, key_concepts,
      simple_tags, semantic_tags, target_audience, actionable_takeaways,
      related_content, transcript,
      content='unified_search_documents', content_rowid='episode_db_id',
      tokenize='porter unicode61 remove_diacritics 2'
    )
        """)
    except Exception:
        # Search still works through unified_search_documents. FTS5 only adds
        # stemming and a small ranking bonus; it is not the source of truth.
        pass
    conn.execute(
        "INSERT OR REPLACE INTO unified_search_meta(key,value) VALUES('schema_version',?)",
        (INDEX_SCHEMA_VERSION,),
    )
    if commit:
        conn.commit()


def _related_values(conn, episode_id: int):
    values={}
    for row in conn.execute("SELECT kind,value FROM episode_terms WHERE episode_id=? ORDER BY kind,value", (episode_id,)):
        values.setdefault(row["kind"], []).append(row["value"])
    for row in conn.execute("SELECT kind,value FROM enrichment_values WHERE episode_id=? ORDER BY kind,value", (episode_id,)):
        values.setdefault(row["kind"], []).append(row["value"])
    topics=[row[0] for row in conn.execute(
        "SELECT t.name FROM episode_topics et JOIN topics t ON t.id=et.topic_id WHERE et.episode_id=? ORDER BY et.is_primary DESC,t.name",
        (episode_id,),
    )]
    quotes=[" | ".join(part for part in row if part) for row in conn.execute(
        "SELECT quote,speaker,topic FROM quotes WHERE episode_id=? ORDER BY id", (episode_id,)
    )]
    emails=[" | ".join(part for part in row if part) for row in conn.execute(
        "SELECT idea,suggested_subject,cta,topic FROM email_ideas WHERE episode_id=? ORDER BY id", (episode_id,)
    )]
    hooks=[" | ".join(part for part in row if part) for row in conn.execute(
        "SELECT hook,topic,exact_or_adapted FROM short_hooks WHERE episode_id=? ORDER BY id", (episode_id,)
    )]
    return values, topics, quotes, emails, hooks


def build_document(conn, episode_id: int) -> dict:
    episode=conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
    if not episode: return {}
    meta=conn.execute("SELECT * FROM episode_enrichment WHERE episode_id=?", (episode_id,)).fetchone()
    meta=dict(meta) if meta else {}
    terms, legacy_topics, quotes, emails, hooks = _related_values(conn, episode_id)
    array=lambda field: _json_list(meta.get(field))
    sources = {
        "episode_number": _unique([episode["episode_id"], str(episode["episode_number"]), f"EP-{episode['episode_number']:03d}"]),
        "title": _unique([episode["episode_title"], meta.get("source_episode_title")]),
        "publish_date": _unique([episode["publish_date"]]),
        "main_category": _unique([meta.get("main_category"), episode["main_category"], episode["main_topic"]]),
        "central_question": _unique([meta.get("central_question")]),
        "summaries": _unique([episode["short_summary"], episode["detailed_summary"]]),
        "main_lesson": _unique([meta.get("core_coaching_theme"), episode["core_coaching_theme"], episode["nicks_main_advice"]]),
        "central_struggle": _unique([meta.get("central_struggle"), episode["central_struggle"], episode["caller_problem"]]),
        "frameworks": _unique([meta.get("primary_nick_framework"), *array("secondary_nick_frameworks"), *array("incidental_nick_concepts"), *terms.get("framework", [])]),
        "key_concepts": _unique([*array("hidden_concepts"), *array("emotional_themes"), *terms.get("hidden_concept", []), *terms.get("semantic_keyword", [])]),
        "simple_tags": _unique([*array("simple_tags"), *terms.get("keyword", [])]),
        "semantic_tags": _unique([*array("topic_tags"), *array("search_queries"), *legacy_topics, *terms.get("search_term", []), *terms.get("topic_tag", [])]),
        "target_audience": _unique(array("target_audience")),
        "actionable_takeaways": _unique([*array("key_takeaways"), *terms.get("key_takeaway", [])]),
        "related_content": _unique([
            meta.get("episode_type"), episode["episode_type"], episode["guest_caller_name"],
            episode["resolution"], episode["cta_recommendation"], *array("caller_questions"),
            *array("myths_debunked"), *array("weight_loss_stage"), *quotes, *emails, *hooks,
            *(value for items in terms.values() for value in items),
        ]),
    }
    document={key:"\n".join(values) for key,values in sources.items()}
    document.update({
        "episode_db_id": episode_id,
        "transcript": episode["transcript"] or "",
        "source_map_json": json.dumps(sources, ensure_ascii=False),
    })
    return document


# Cheap change-detection signal. Each expression is a server-side aggregate
# (COUNT / MAX / SUM(LENGTH(...))) that returns a single number, so the whole
# signature is one round trip that never transfers transcripts or other content.
# It detects inserts, deletes, and edits to indexed text; application writes also
# refresh this signature directly so the startup fast-path stays valid.
_SIGNATURE_EXPRESSIONS = [
    ("episodes", "COUNT(*)"),
    ("episodes", "IFNULL(MAX(id),0)"),
    ("episodes", "IFNULL(SUM(LENGTH(COALESCE(transcript,''))),0)"),
    ("episodes",
     "IFNULL(SUM(LENGTH(COALESCE(episode_title,''))+LENGTH(COALESCE(short_summary,''))"
     "+LENGTH(COALESCE(detailed_summary,''))+LENGTH(COALESCE(nicks_main_advice,''))"
     "+LENGTH(COALESCE(caller_problem,''))+LENGTH(COALESCE(main_category,''))"
     "+LENGTH(COALESCE(central_struggle,''))+LENGTH(COALESCE(core_coaching_theme,''))),0)"),
    ("episode_enrichment", "COUNT(*)"),
    ("episode_enrichment",
     "IFNULL(SUM(LENGTH(COALESCE(source_episode_title,''))+LENGTH(COALESCE(central_question,''))"
     "+LENGTH(COALESCE(central_struggle,''))+LENGTH(COALESCE(core_coaching_theme,''))"
     "+LENGTH(COALESCE(primary_nick_framework,''))+LENGTH(COALESCE(main_category,''))"
     "+LENGTH(COALESCE(simple_tags,''))+LENGTH(COALESCE(topic_tags,''))"
     "+LENGTH(COALESCE(key_takeaways,''))+LENGTH(COALESCE(secondary_nick_frameworks,''))),0)"),
    ("enrichment_values", "COUNT(*)"),
    ("enrichment_values", "IFNULL(SUM(LENGTH(COALESCE(value,''))),0)"),
    ("episode_terms", "COUNT(*)"),
    ("episode_terms", "IFNULL(SUM(LENGTH(COALESCE(value,''))),0)"),
    ("episode_topics", "COUNT(*)"),
    ("episode_topics", "IFNULL(SUM(COALESCE(topic_id,0)),0)"),
    ("episode_topics", "IFNULL(SUM(COALESCE(is_primary,0)),0)"),
    ("topics", "COUNT(*)"),
    ("topics", "IFNULL(SUM(LENGTH(COALESCE(name,''))),0)"),
    ("quotes", "COUNT(*)"),
    ("quotes", "IFNULL(MAX(id),0)"),
    ("quotes", "IFNULL(SUM(LENGTH(COALESCE(quote,''))+LENGTH(COALESCE(speaker,''))+LENGTH(COALESCE(topic,''))),0)"),
    ("email_ideas", "COUNT(*)"),
    ("email_ideas", "IFNULL(MAX(id),0)"),
    ("email_ideas",
     "IFNULL(SUM(LENGTH(COALESCE(idea,''))+LENGTH(COALESCE(suggested_subject,''))"
     "+LENGTH(COALESCE(cta,''))+LENGTH(COALESCE(topic,''))),0)"),
    ("short_hooks", "COUNT(*)"),
    ("short_hooks", "IFNULL(MAX(id),0)"),
    ("short_hooks", "IFNULL(SUM(LENGTH(COALESCE(hook,''))+LENGTH(COALESCE(exact_or_adapted,''))+LENGTH(COALESCE(topic,''))),0)"),
]
SIGNATURE_SQL = "SELECT " + ", ".join(f"(SELECT {expr} FROM {table})" for table, expr in _SIGNATURE_EXPRESSIONS)


def source_signature(conn) -> str:
    row = conn.execute(SIGNATURE_SQL).fetchone()
    parts = [INDEX_VERSION, *("" if value is None else str(value) for value in row)]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def rebuild_index(conn, *, commit: bool = True) -> int:
    # CRUD calls use commit=False inside an existing transaction. The schema is
    # guaranteed by application startup; avoiding executescript here preserves
    # the caller's transaction boundary on sqlite3 and libsql alike.
    if commit:
        create_schema(conn, commit=False)
    signature=source_signature(conn)
    conn.execute("DELETE FROM unified_search_documents")
    columns=["episode_db_id", *INDEX_COLUMNS, "source_map_json"]
    placeholders=",".join("?" for _ in columns)
    count=0
    for row in conn.execute("SELECT id FROM episodes ORDER BY id"):
        document=build_document(conn, row[0])
        conn.execute(
            f"INSERT INTO unified_search_documents({','.join(columns)}) VALUES({placeholders})",
            [document.get(column, "") for column in columns],
        )
        count+=1
    try:
        conn.execute("INSERT INTO unified_episode_search(unified_episode_search) VALUES('rebuild')")
    except Exception:
        # Optional FTS maintenance must never prevent the portable document
        # index from becoming available on remote libsql deployments.
        pass
    conn.execute("INSERT OR REPLACE INTO unified_search_meta(key,value) VALUES('signature',?)", (signature,))
    conn.execute("INSERT OR REPLACE INTO unified_search_meta(key,value) VALUES('version',?)", (INDEX_VERSION,))
    if commit:
        conn.commit()
    return count


def portable_index_is_usable(conn) -> bool:
    """Return whether the read-only document index covers every episode."""
    try:
        episode_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        index_count = conn.execute("SELECT COUNT(*) FROM unified_search_documents").fetchone()[0]
        return episode_count == index_count and episode_count > 0
    except Exception:
        return False


def _index_state(conn):
    """Return counts, schema version, and stored signature in one round trip.

    Returns None when the index tables are absent, signalling a first build.
    """
    try:
        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM episodes),"
            " (SELECT COUNT(*) FROM unified_search_documents),"
            " (SELECT value FROM unified_search_meta WHERE key='schema_version'),"
            " (SELECT value FROM unified_search_meta WHERE key='signature')"
        ).fetchone()
    except Exception:
        return None
    return {"episodes": row[0], "documents": row[1], "schema_version": row[2], "signature": row[3]}


def ensure_index(conn) -> bool:
    try:
        state = _index_state(conn)
        if state is None:
            rebuild_index(conn)  # creates the schema and builds every document
            return True
        signature = source_signature(conn)
        schema_current = state["schema_version"] == INDEX_SCHEMA_VERSION
        complete = state["episodes"] == state["documents"] and state["episodes"] > 0
        if schema_current and complete and state["signature"] == signature:
            return False
        if schema_current and complete and state["signature"] is None:
            # Upgrade path: a complete index maintained by an earlier version has
            # no stored signature yet. Trust it and record the cheap signature
            # instead of paying for one full rebuild after deploying this change.
            conn.execute("INSERT OR REPLACE INTO unified_search_meta(key,value) VALUES('signature',?)", (signature,))
            conn.commit()
            return False
        rebuild_index(conn)
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # A migrated Turso database can already have a complete portable index
        # while its token or remote protocol disallows startup DDL/FTS upkeep.
        # Reads remain correct, so do not make optional maintenance fatal.
        if portable_index_is_usable(conn):
            return False
        raise


def _fts_forget(conn, document_row) -> None:
    """Best-effort removal of an episode's old terms from the external-content FTS."""
    if document_row is None:
        return
    try:
        conn.execute(
            f"INSERT INTO unified_episode_search(unified_episode_search, rowid, {','.join(INDEX_COLUMNS)}) "
            f"VALUES('delete', ?, {','.join('?' for _ in INDEX_COLUMNS)})",
            [document_row["episode_db_id"], *[document_row[column] or "" for column in INDEX_COLUMNS]],
        )
    except Exception:
        pass


def _fts_index(conn, episode_id: int, document: dict) -> None:
    """Best-effort insert of an episode's terms into the external-content FTS."""
    try:
        conn.execute(
            f"INSERT INTO unified_episode_search(rowid, {','.join(INDEX_COLUMNS)}) "
            f"VALUES(?, {','.join('?' for _ in INDEX_COLUMNS)})",
            [episode_id, *[document.get(column, "") for column in INDEX_COLUMNS]],
        )
    except Exception:
        pass


def refresh_episode(conn, episode_id: int, *, commit: bool = True) -> None:
    """Update just this episode's search document in place.

    A single-row update keeps CRUD fast over the remote database; a full rebuild
    of all documents happens only at startup or on a schema change. The stored
    signature is refreshed so the next startup takes the no-rebuild fast path.
    """
    old = conn.execute(
        "SELECT * FROM unified_search_documents WHERE episode_db_id=?", (episode_id,)
    ).fetchone()
    document = build_document(conn, episode_id)
    _fts_forget(conn, old)
    if not document:
        conn.execute("DELETE FROM unified_search_documents WHERE episode_db_id=?", (episode_id,))
    else:
        columns = ["episode_db_id", *INDEX_COLUMNS, "source_map_json"]
        conn.execute(
            f"INSERT OR REPLACE INTO unified_search_documents({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in columns)})",
            [document.get(column, "") for column in columns],
        )
        _fts_index(conn, episode_id, document)
    conn.execute(
        "INSERT OR REPLACE INTO unified_search_meta(key,value) VALUES('signature',?)", (source_signature(conn),)
    )
    if commit:
        conn.commit()


def _query_terms(query: str):
    normalized=normalize(query)
    tokens=[token for token in normalized.split() if token not in STOP_WORDS and len(token)>1]
    expansions=[]
    for trigger,values in SEMANTIC_EXPANSIONS.items():
        if trigger in normalized or normalized in trigger:
            expansions.extend(values)
    return normalized, list(dict.fromkeys(tokens)), _unique(expansions)


def _fts_ranks(conn, tokens, expansions):
    terms=[]
    for token in [*tokens, *(part for phrase in expansions for part in normalize(phrase).split())]:
        if token.isalnum() and token not in STOP_WORDS: terms.append(f'"{token}"*')
    if not terms: return {}
    expression=" OR ".join(dict.fromkeys(terms))
    weights=[FIELD_WEIGHTS[column] for column in INDEX_COLUMNS]
    sql=f"SELECT rowid,bm25(unified_episode_search,{','.join(str(value) for value in weights)}) rank FROM unified_episode_search WHERE unified_episode_search MATCH ?"
    try:
        return {row[0]:abs(float(row[1])) for row in conn.execute(sql,(expression,))}
    except Exception:
        return {}


def _snippet(text: str, query: str, tokens) -> str:
    normalized_text=normalize(text)
    position=normalized_text.find(query) if query else -1
    if position < 0:
        positions=[normalized_text.find(token) for token in tokens if normalized_text.find(token)>=0]
        position=min(positions) if positions else 0
    # Normalization can shift accents slightly; this bounded excerpt remains safe and useful.
    start=max(0,position-140); excerpt=text[start:start+520].replace("\n"," ").strip()
    return html.escape(excerpt)


def _tokens_nearby(text: str, tokens: list[str], max_span: int = 180) -> bool:
    """Require a multi-word transcript query to occur in one coherent passage."""
    if len(tokens) < 2:
        return bool(tokens and tokens[0] in text)
    positions=[]
    for token in tokens:
        found=[match.start() for match in re.finditer(rf"\b{re.escape(token)}\b",text)][:60]
        if not found: return False
        positions.append(found)
    events=sorted((position,index) for index,items in enumerate(positions) for position in items)
    counts={}; left=0
    for right,(position,index) in enumerate(events):
        counts[index]=counts.get(index,0)+1
        while len(counts)==len(tokens):
            if position-events[left][0] <= max_span: return True
            left_index=events[left][1]; counts[left_index]-=1
            if not counts[left_index]: del counts[left_index]
            left+=1
    return False


def search(conn, query: str) -> list[dict]:
    if not portable_index_is_usable(conn):
        create_schema(conn)
    query_norm,tokens,expansions=_query_terms(query)
    if not query_norm: return []
    fts_ranks=_fts_ranks(conn,tokens,expansions)
    results=[]
    for row in conn.execute("SELECT * FROM unified_search_documents ORDER BY episode_db_id"):
        sources=json.loads(row["source_map_json"] or "{}")
        best_score=0.0; best_reason=""; best_snippet=""; literal_match=False
        for field in INDEX_COLUMNS:
            values=[row[field]] if field=="transcript" else sources.get(field,[])
            for value in values:
                value_norm=normalize(value)
                if not value_norm: continue
                score=0.0; match_kind=""
                if query_norm == value_norm:
                    score=FIELD_WEIGHTS[field]*120; match_kind="exact"
                elif query_norm in value_norm:
                    score=FIELD_WEIGHTS[field]*100; match_kind="phrase"
                else:
                    hits=sum(token in value_norm for token in tokens)
                    prefix_hits=sum(any(word.startswith(token) or token.startswith(word) for word in value_norm.split()) for token in tokens)
                    # A multi-word query must match all meaningful words in the same
                    # structured field, or within one nearby transcript passage.
                    coherent = len(tokens)<=1 or hits==len(tokens) or (field=="transcript" and _tokens_nearby(value_norm,tokens))
                    if hits and coherent:
                        score=FIELD_WEIGHTS[field]*(3+5*hits/max(1,len(tokens))); match_kind="partial"
                    elif prefix_hits and (len(tokens)<=1 or prefix_hits==len(tokens)):
                        score=FIELD_WEIGHTS[field]*(2+3*prefix_hits/max(1,len(tokens))); match_kind="partial"
                if score:
                    literal_match=True
                    if score>best_score:
                        label=FIELD_LABELS[field]
                        shown=str(value).strip()
                        best_score=score
                        best_reason=f"Matched {label}: {shown[:150]}" if field not in {"transcript","summaries","main_lesson","central_question","central_struggle","actionable_takeaways"} else f"Matched {label}"
                        best_snippet=_snippet(str(value),query_norm,tokens) if field=="transcript" else html.escape(shown[:420])
        semantic_score=0.0; semantic_reason=""
        for phrase in expansions:
            phrase_norm=normalize(phrase)
            for field in INDEX_COLUMNS[:-1]:
                for value in sources.get(field,[]):
                    if phrase_norm and phrase_norm in normalize(value):
                        candidate=FIELD_WEIGHTS[field]*6
                        if candidate>semantic_score:
                            semantic_score=candidate
                            semantic_reason=f"Conceptually related {FIELD_LABELS[field]}: {str(value)[:150]}"
        fts_bonus=min(80.0,fts_ranks.get(row["episode_db_id"],0.0)*4)
        total=best_score+semantic_score+fts_bonus
        if total>0 and (literal_match or semantic_score>0):
            results.append({
                "episode_db_id":row["episode_db_id"], "score":round(total,3),
                "reason":best_reason or semantic_reason or "Matched unified full-text index",
                "snippet":best_snippet, "literal_match":literal_match,
            })
    return sorted(results,key=lambda item:(-item["score"],item["episode_db_id"]))
