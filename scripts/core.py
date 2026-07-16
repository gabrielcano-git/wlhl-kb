from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.json"
DB_PATH = PROJECT_ROOT / "database.sqlite"
EXPORT_DIR = PROJECT_ROOT / "database"

ARRAY_FIELDS = [
    "secondary_topics", "topic_tags", "semantic_keywords", "key_takeaways",
    "memorable_quotes", "potential_email_angles", "suggested_email_subject_lines",
    "potential_short_hooks", "relevant_audience", "emotional_themes",
    "hidden_concepts", "incidental_concepts_mentioned", "search_terms",
]

FIELDS = [
    "episode_id", "episode_number", "episode_title", "publish_date", "youtube_url",
    "transcript_filename", "relative_transcript_path", "episode_type", "guest_caller_name",
    "main_topic", "secondary_topics", "topic_tags", "semantic_keywords", "short_summary",
    "detailed_summary", "key_takeaways", "nicks_main_advice", "caller_problem", "resolution",
    "memorable_quotes", "potential_email_angles", "suggested_email_subject_lines",
    "potential_short_hooks", "relevant_audience", "emotional_themes", "weight_loss_stage",
    "cta_recommendation", "transcript_status", "review_notes", "main_category", "search_terms",
    "hidden_concepts", "central_struggle", "core_coaching_theme", "incidental_concepts_mentioned",
    "success_story", "transcript", "source_hash", "source_mtime", "processed_at",
]

VOCAB = {
    "emotional eating": ["emotional eating", "eating my feelings", "face yourself instead of the fridge"],
    "binge eating": ["binge eating", "binge"],
    "weight loss plateau": ["plateau", "scale just won't go down", "scale just won’t go down"],
    "fear of regain": ["gain the weight back", "keep the weight off", "regain"],
    "maintenance mindset": ["maintenance", "keep the weight off", "kept it off"],
    "all-or-nothing thinking": ["all or nothing", "starting over", "day 1", "start my diet tomorrow"],
    "cravings": ["craving", "food noise"],
    "body image": ["hate your body", "body image", "skinny privilege"],
    "identity change": ["identity", "fat mind", "thinking like a fat person", "old fat self"],
    "consistency": ["consistency", "stopped quitting", "momentum", "routine"],
    "sustainable habits": ["sustainable", "permanent", "routine", "habit makes"],
    "self-sabotage": ["self-sabotage", "self sabotage", "excuses"],
    "scale obsession": ["scale", "non-scale victories"],
    "restaurant eating": ["eat out", "restaurant"],
    "weekend overeating": ["weekend"],
    "social pressure": ["social", "friendship", "family conflict"],
    "exercise routine": ["workout", "exercise routine", "working out"],
    "calorie tracking": ["counting calories", "calories in"],
    "food guilt": ["cheat meal", "war with", "relationship with food"],
    "motivation": ["motivated", "motivation", "willpower"],
    "comparison": ["competition", "comparison"],
    "confidence": ["confidence", "imposter syndrome", "skinny privilege"],
    "grief": ["grief", "loss of", "died"],
    "nutrition": ["diet coke", "food swaps", "intuitively", "low calorie", "common sense diet"],
    "relationships": ["relationship", "partner", "dating", "sex"],
    "medication": ["ozempic", "weight loss shot"],
}

CATEGORY_MAP = {
    "emotional eating": "Emotional Eating", "binge eating": "Emotional Eating",
    "weight loss plateau": "Plateau", "fear of regain": "Weight Loss Maintenance",
    "maintenance mindset": "Weight Loss Maintenance", "exercise routine": "Exercise",
    "nutrition": "Nutrition", "relationships": "Relationships", "medication": "Nutrition",
}

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def transcript_dir() -> Path:
    portable = PROJECT_ROOT / "transcripts"
    if portable.exists() and any(portable.glob("*.txt")):
        return portable.resolve()
    return (PROJECT_ROOT / load_config()["transcript_directory"]).resolve()

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_file(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = raw.splitlines()
    fname_match = re.search(r"EP-(\d{3})", path.name)
    if not fname_match:
        raise ValueError("Filename has no canonical EP-### number")
    number = int(fname_match.group(1))
    episode_id = f"EP-{number:03d}"
    first = lines[0].strip() if lines else ""
    url_match = re.search(r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[^\s)]+", raw)
    date_matches = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", first)
    publish_date = date_matches[-1] if date_matches else ""
    parts = [p.strip() for p in first.split("|")]
    header_ids = re.findall(r"EP-(\d{3})", first)
    title = ""
    if len(parts) >= 2:
        title = parts[1].strip(' "')
    if not title:
        title = re.sub(r"^EP-\d{3}\s*-\s*", "", path.stem)
        title = re.sub(r"\s*-\s*(?:EP\s*\d{3}|#\d{3})$", "", title).strip()
    sep = next((i for i, line in enumerate(lines) if line.strip() == "---"), None)
    transcript = "\n".join(lines[sep + 1:]).strip() if sep is not None else "\n".join(lines[2:]).strip()
    notes = []
    if not raw.strip(): notes.append("Empty transcript")
    if sep is None: notes.append("Missing transcript separator")
    if not url_match: notes.append("Missing YouTube URL")
    if not publish_date: notes.append("Missing publish date")
    if header_ids and f"{number:03d}" not in header_ids:
        notes.append(f"Header episode number conflicts with canonical filename ({', '.join(header_ids)})")
    elif header_ids and header_ids[0] != f"{number:03d}":
        notes.append(f"First header episode number conflicts with canonical filename ({header_ids[0]})")
    if len(transcript) < 500: notes.append("Transcript appears incomplete")
    try:
        relative_source = path.relative_to(PROJECT_ROOT)
    except ValueError:
        relative_source = Path("..") / path.parent.name / path.name
    return {
        "episode_id": episode_id, "episode_number": number, "episode_title": title,
        "publish_date": publish_date, "youtube_url": url_match.group(0) if url_match else "",
        "transcript_filename": path.name,
        "relative_transcript_path": relative_source,
        "transcript": transcript, "review_notes": notes,
    }

def classify(record: dict) -> dict:
    title = record["episode_title"].lower()
    text_start = record["transcript"][:12000].lower()
    supported = title + "\n" + text_start
    scored = []
    for tag, phrases in VOCAB.items():
        score = sum(4 if p in title else min(supported.count(p), 3) for p in phrases)
        if score: scored.append((score, tag))
    scored.sort(key=lambda x: (-x[0], x[1]))
    tags = [t for _, t in scored[:6]]
    main = tags[0] if tags else "Unknown"
    category = CATEGORY_MAP.get(main, "Mindset" if main not in ("Unknown", "nutrition") else ("Unknown" if main == "Unknown" else "Nutrition"))
    is_success = bool(re.search(r"lost \d+|success|kept it off|pounds later|non-scale victor", title))
    if is_success and main == "Unknown": category = "Success Story"
    episode_type = "Live" if "live" in title else "Q&A" if "q&a" in title or "questions" in title else "Success Story" if is_success else "Solo"
    terms = []
    for tag in tags:
        terms.extend({
            "fear of regain": ["scared to gain the weight back", "how to maintain weight loss"],
            "emotional eating": ["why do I eat my feelings", "how to stop emotional eating"],
            "binge eating": ["why can't I stop binge eating", "breaking binge cycles"],
            "weight loss plateau": ["scale hasn't moved in weeks", "what to do during a weight loss plateau"],
            "all-or-nothing thinking": ["I keep restarting every Monday", "how to stop starting over"],
            "identity change": ["how to stop thinking like a fat person", "identity change after weight loss"],
            "consistency": ["I know what to do but I don't do it", "consistency over perfection"],
            "cravings": ["how to stop food noise", "why can't I eat just one"],
        }.get(tag, [tag]))
    terms = list(dict.fromkeys(terms))[:12]
    notes = list(record["review_notes"])
    notes.append("Semantic enrichment is provisional: title and limited transcript evidence only; human/AI review recommended")
    short_summary = f"An episode centered on {main}." if main != "Unknown" else "Summary requires semantic review."
    return {
        **record,
        "episode_type": episode_type, "guest_caller_name": "", "main_topic": main,
        "secondary_topics": tags[1:], "topic_tags": tags, "semantic_keywords": terms[:15],
        "short_summary": short_summary, "detailed_summary": "", "key_takeaways": [],
        "nicks_main_advice": "", "caller_problem": "", "resolution": "", "memorable_quotes": [],
        "potential_email_angles": [], "suggested_email_subject_lines": [], "potential_short_hooks": [],
        "relevant_audience": [], "emotional_themes": [], "weight_loss_stage": "Unknown",
        "cta_recommendation": "", "transcript_status": "Review Required" if notes else "Complete",
        "review_notes": notes, "main_category": category, "search_terms": terms,
        "hidden_concepts": [], "central_struggle": "", "core_coaching_theme": "",
        "incidental_concepts_mentioned": [], "success_story": is_success,
    }

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS episodes (
      id INTEGER PRIMARY KEY, episode_id TEXT NOT NULL, episode_number INTEGER NOT NULL,
      episode_title TEXT, publish_date TEXT, youtube_url TEXT, transcript_filename TEXT NOT NULL UNIQUE,
      relative_transcript_path TEXT, episode_type TEXT, guest_caller_name TEXT, main_topic TEXT,
      main_category TEXT, short_summary TEXT, detailed_summary TEXT, nicks_main_advice TEXT,
      caller_problem TEXT, resolution TEXT, weight_loss_stage TEXT, cta_recommendation TEXT,
      transcript_status TEXT, review_notes TEXT, central_struggle TEXT, core_coaching_theme TEXT,
      success_story INTEGER, transcript TEXT, source_hash TEXT, source_mtime REAL, processed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS topics (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS episode_topics (episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE, topic_id INTEGER REFERENCES topics(id), is_primary INTEGER DEFAULT 0, PRIMARY KEY(episode_id,topic_id));
    CREATE TABLE IF NOT EXISTS episode_terms (episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE, kind TEXT, value TEXT, PRIMARY KEY(episode_id,kind,value));
    CREATE TABLE IF NOT EXISTS quotes (id INTEGER PRIMARY KEY, episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE, quote TEXT, speaker TEXT, topic TEXT);
    CREATE TABLE IF NOT EXISTS email_ideas (id INTEGER PRIMARY KEY, episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE, topic TEXT, idea TEXT, suggested_subject TEXT, cta TEXT);
    CREATE TABLE IF NOT EXISTS short_hooks (id INTEGER PRIMARY KEY, episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE, topic TEXT, hook TEXT, exact_or_adapted TEXT);
    CREATE TABLE IF NOT EXISTS processing_issues (id INTEGER PRIMARY KEY, episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE, issue_type TEXT, detail TEXT, created_at TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS episode_search USING fts5(episode_db_id UNINDEXED, title, summaries, takeaways, nicks_advice, caller_problem, transcript, keywords, quotes, topics, callers, tokenize='porter unicode61');
    """)

def save_record(conn: sqlite3.Connection, rec: dict) -> None:
    row = conn.execute("SELECT id FROM episodes WHERE transcript_filename=?", (rec["transcript_filename"],)).fetchone()
    dbcols = ["episode_id","episode_number","episode_title","publish_date","youtube_url","transcript_filename","relative_transcript_path","episode_type","guest_caller_name","main_topic","main_category","short_summary","detailed_summary","nicks_main_advice","caller_problem","resolution","weight_loss_stage","cta_recommendation","transcript_status","review_notes","central_struggle","core_coaching_theme","success_story","transcript","source_hash","source_mtime","processed_at"]
    vals = [json.dumps(rec[c], ensure_ascii=False) if c == "review_notes" else str(rec[c]) if c == "relative_transcript_path" else int(rec[c]) if c == "success_story" else rec[c] for c in dbcols]
    if row:
        eid=row[0]; conn.execute("UPDATE episodes SET "+",".join(f"{c}=?" for c in dbcols)+" WHERE id=?", vals+[eid])
        conn.execute("DELETE FROM episode_topics WHERE episode_id=?",(eid,)); conn.execute("DELETE FROM episode_terms WHERE episode_id=?",(eid,)); conn.execute("DELETE FROM processing_issues WHERE episode_id=?",(eid,)); conn.execute("DELETE FROM episode_search WHERE episode_db_id=?",(eid,))
    else:
        q=",".join("?" for _ in dbcols); cur=conn.execute(f"INSERT INTO episodes ({','.join(dbcols)}) VALUES ({q})",vals); eid=cur.lastrowid
    for i, topic in enumerate(rec["topic_tags"]):
        conn.execute("INSERT OR IGNORE INTO topics(name) VALUES(?)",(topic,)); tid=conn.execute("SELECT id FROM topics WHERE name=?",(topic,)).fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO episode_topics VALUES(?,?,?)",(eid,tid,int(i==0)))
    for kind, field in [("keyword","semantic_keywords"),("search_term","search_terms"),("hidden_concept","hidden_concepts"),("secondary_topic","secondary_topics")]:
        for value in rec[field]: conn.execute("INSERT OR IGNORE INTO episode_terms VALUES(?,?,?)",(eid,kind,value))
    for note in rec["review_notes"]: conn.execute("INSERT INTO processing_issues(episode_id,issue_type,detail,created_at) VALUES(?,?,?,?)",(eid,"Review",note,rec["processed_at"]))
    conn.execute("INSERT INTO episode_search VALUES(?,?,?,?,?,?,?,?,?,?,?)",(eid,rec["episode_title"],rec["short_summary"]+" "+rec["detailed_summary"]," ".join(rec["key_takeaways"]),rec["nicks_main_advice"],rec["caller_problem"],rec["transcript"]," ".join(rec["semantic_keywords"]+rec["search_terms"]+rec["hidden_concepts"])," ".join(rec["memorable_quotes"])," ".join(rec["topic_tags"]),rec["guest_caller_name"]))

def process(force=False) -> dict:
    td=transcript_dir(); files=sorted(td.glob("*.txt"), key=lambda p:(int(re.search(r"EP-(\d+)",p.name).group(1)),p.name))
    conn=connect(); init_db(conn); processed=0; skipped=0; errors=[]
    for path in files:
        digest=sha256(path)
        old=conn.execute("SELECT source_hash FROM episodes WHERE transcript_filename=?",(path.name,)).fetchone()
        if old and old[0]==digest and not force: skipped+=1; continue
        try:
            rec=classify(parse_file(path)); rec["source_hash"]=digest; rec["source_mtime"]=path.stat().st_mtime; rec["processed_at"]=datetime.now().isoformat(timespec="seconds")
            save_record(conn,rec); conn.commit(); processed+=1
        except Exception as e:
            errors.append(f"{path.name}: {e}")
    numbers=Counter(int(re.search(r"EP-(\d+)",p.name).group(1)) for p in files)
    duplicates=sorted(n for n,count in numbers.items() if count>1)
    for n in duplicates:
        for row in conn.execute("SELECT id FROM episodes WHERE episode_number=?",(n,)):
            detail=f"Duplicate canonical episode number EP-{n:03d}"
            if not conn.execute("SELECT 1 FROM processing_issues WHERE episode_id=? AND detail=?",(row[0],detail)).fetchone():
                conn.execute("INSERT INTO processing_issues(episode_id,issue_type,detail,created_at) VALUES(?,?,?,?)",(row[0],"Duplicate",detail,datetime.now().isoformat(timespec="seconds")))
    conn.commit(); stats={"files_found":len(files),"processed":processed,"skipped":skipped,"errors":errors,"duplicate_episode_numbers":[f"EP-{n:03d}" for n in duplicates]}; write_exports(conn,stats); conn.commit(); shutil.copy2(DB_PATH,EXPORT_DIR/"WLHL_Episode_Database.sqlite"); conn.close(); return stats

def records_from_db(conn):
    out=[]
    for row in conn.execute("SELECT * FROM episodes ORDER BY episode_number, transcript_filename"):
        r=dict(row); eid=r.pop("id")
        for f in ARRAY_FIELDS: r[f]=[]
        terms=conn.execute("SELECT kind,value FROM episode_terms WHERE episode_id=? ORDER BY kind,value",(eid,)).fetchall()
        for t in terms:
            dest={"keyword":"semantic_keywords","search_term":"search_terms","hidden_concept":"hidden_concepts","secondary_topic":"secondary_topics"}.get(t["kind"])
            if dest:r[dest].append(t["value"])
        r["topic_tags"]=[x[0] for x in conn.execute("SELECT t.name FROM episode_topics et JOIN topics t ON t.id=et.topic_id WHERE et.episode_id=? ORDER BY et.is_primary DESC,t.name",(eid,))]
        r["review_notes"]=json.loads(r["review_notes"] or "[]"); r["success_story"]=bool(r["success_story"]); out.append(r)
    return out

def write_exports(conn,stats):
    EXPORT_DIR.mkdir(exist_ok=True); episodes=records_from_db(conn)
    (EXPORT_DIR/"WLHL_Episode_Database.json").write_text(json.dumps(episodes,ensure_ascii=False,indent=2),encoding="utf-8")
    (EXPORT_DIR/"episodes.json").write_text(json.dumps(episodes,ensure_ascii=False,indent=2),encoding="utf-8")
    topics=[]
    for row in conn.execute("SELECT t.name,COUNT(*) c FROM topics t JOIN episode_topics et ON et.topic_id=t.id GROUP BY t.id ORDER BY c DESC,t.name"):
        eps=[x[0] for x in conn.execute("SELECT e.episode_id FROM episode_topics et JOIN episodes e ON e.id=et.episode_id WHERE et.topic_id=(SELECT id FROM topics WHERE name=?) ORDER BY e.episode_number",(row[0],))]
        topics.append({"topic":row[0],"number_of_episodes":row[1],"episode_numbers":eps})
    for name,data in [("topics.json",topics),("quotes.json",[]),("email_ideas.json",[]),("hooks.json",[])]: (EXPORT_DIR/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    csv_fields=[f for f in FIELDS if f not in ("transcript","source_hash","source_mtime","processed_at")]
    for filename in ["WLHL_Episode_Database.csv"]:
        with (EXPORT_DIR/filename).open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=csv_fields); w.writeheader()
            for r in episodes:w.writerow({k:json.dumps(r.get(k,[]),ensure_ascii=False) if isinstance(r.get(k),list) else r.get(k,"") for k in csv_fields})
    (PROJECT_ROOT/"processing_log.txt").write_text(json.dumps(stats,indent=2)+"\n",encoding="utf-8")

def search(query, limit=20):
    conn=connect(); q=' OR '.join(f'"{p}"' for p in re.findall(r"[\w’'-]+",query) if p)
    if not q:return []
    rows=conn.execute("SELECT e.*,bm25(episode_search,10,5,3,4,4,1,5,4,6,4) score,snippet(episode_search,6,'[',']',' … ',24) snippet FROM episode_search JOIN episodes e ON e.id=episode_search.episode_db_id WHERE episode_search MATCH ? ORDER BY score LIMIT ?",(q,limit)).fetchall()
    conn.close(); return [dict(r) for r in rows]
