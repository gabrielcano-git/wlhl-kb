"""Local persistence, source extraction, and prompt assembly for WLHL."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime

from prompt_templates import TEMPLATES_BY_ID


MASTER_PROMPT = """The WLHL Knowledge Base exists to transform every podcast episode into a searchable marketing asset.

Its purpose is to make years of podcast content instantly reusable for email marketing, newsletters, YouTube videos, YouTube Shorts, social media, landing pages, sales pages, lead magnets, community posts, and future AI-powered workflows.

The Knowledge Base should always be treated as the primary source of truth for all marketing content.

You are the dedicated AI marketing assistant for The Weight Loss Hotline.

The supplied Knowledge Base information and transcript material are your primary sources of truth. Always use them before relying on general knowledge.

Your responsibility is to create marketing assets that faithfully represent Nick’s voice, philosophy, experience, and coaching style."""

DEFAULT_SETTINGS = {
    "master_prompt": MASTER_PROMPT,
    "source_priority": "Episode transcripts\nEpisode database\nExisting WLHL documentation\nGeneral knowledge\n\nIf there is any conflict between the episode database and the transcript, trust the transcript.",
    "research_rules": "Review the supplied episode material.\nIdentify the strongest relevant ideas.\nIdentify supporting stories, examples, quotes, and concepts.\nBase the final work on the selected episodes.\nNever invent missing information.",
    "nick_voice": "Honest\nPractical\nCompassionate\nDirect\nEncouraging\nPersonal\nClear\nLong-term focused\nGrounded in lived experience\nEvidence-informed without sounding academic\n\nNick speaks like a real person talking directly to one individual. He explains rather than lectures. He is emotionally honest without becoming overly dramatic. He challenges people without shaming them. He favors clarity over cleverness. He does not sound like a guru, motivational speaker, corporate brand, or generic fitness coach.",
    "wlhl_philosophy": "Sustainable behavior matters more than temporary results.\nWeight loss should not require living in permanent restriction.\nConsistency matters more than perfection.\nThe goal is not to hate yourself into becoming healthier.\nFood should not be treated as a moral issue.\nA setback does not erase progress.\nLong-term identity and behavior change matter more than quick fixes.\nAdvice should be practical enough to use in real life.\nWeight loss content should acknowledge emotional, social, and behavioral realities.",
    "content_rules": "Always ground ideas in actual podcast material.\nPreserve the original intent of Nick’s advice.\nUse Nick’s natural language when appropriate.\nStay consistent with the selected episodes.\nMake the content useful and specific.\nDistinguish between what Nick explicitly said and what is being summarized.\n\nNever invent podcast episodes, quotes, personal stories, facts, studies, statistics, or results. Never attribute unsupported ideas to Nick, exaggerate claims, add generic motivational filler, use shame or manipulation, or promise guaranteed or unrealistic outcomes. If the supplied material is insufficient, clearly state that instead of guessing.",
    "forbidden_language": "Unlock your potential\nTransform your life\nRevolutionary\nGame-changing\nSecret\nHack\nBreakthrough\nEffortless\nGuaranteed\nLose weight fast\nNo excuses\nSummer body\nCheat day\nBad food\nGood food",
    "preferred_language": "Build\nPractice\nLearn\nNotice\nUnderstand\nExperiment\nSustainable\nRealistic\nConsistent\nLong-term\nHealthy relationship\nHealthy mind\nDaily behavior\nPractical\nProgress",
    "cta_rules": "CTAs should feel like invitations, not pressure.\nAvoid fake urgency and aggressive sales language.\nKeep the CTA relevant to the content.\nDo not force a sales CTA into educational content.\nWhen appropriate, invite the audience to listen to the full episode.\nDo not claim that an episode contains information that is not actually discussed.",
    "formatting_rules": "Use natural paragraph lengths.\nAvoid excessive bullet points unless the content type requires them.\nAvoid unnecessary headings.\nDo not use fake quotes.\nDo not overuse em dashes.\nDo not use Title Case for every heading.\nKeep the writing easy to scan.\nMatch the requested platform and format.",
    "content_type_instructions": {template_id: template.default_instructions for template_id, template in TEMPLATES_BY_ID.items()},
}

SETTING_LABELS = {
    "master_prompt": "WLHL AI Master Prompt",
    "source_priority": "Source priority",
    "research_rules": "Research rules",
    "nick_voice": "Nick’s voice",
    "wlhl_philosophy": "WLHL philosophy",
    "content_rules": "Content rules",
    "forbidden_language": "Language to avoid",
    "preferred_language": "Preferred language",
    "cta_rules": "CTA rules",
    "formatting_rules": "Formatting rules",
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS prompt_settings (
      id INTEGER PRIMARY KEY CHECK(id=1), settings_json TEXT NOT NULL, last_mode TEXT NOT NULL DEFAULT 'Quick Prompt', updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS prompt_presets (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, content_type TEXT NOT NULL,
      configuration_json TEXT NOT NULL, include_episodes INTEGER NOT NULL DEFAULT 0,
      selected_episode_ids TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS prompt_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, content_type TEXT NOT NULL,
      topic TEXT, selected_episode_ids TEXT NOT NULL, generated_prompt TEXT NOT NULL, configuration_json TEXT NOT NULL
    );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO prompt_settings(id,settings_json,last_mode,updated_at) VALUES(1,?,'Quick Prompt',?)",
        (json.dumps(DEFAULT_SETTINGS, ensure_ascii=False), _now()),
    )
    conn.commit()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_settings(conn) -> dict:
    init_schema(conn)
    row = conn.execute("SELECT settings_json FROM prompt_settings WHERE id=1").fetchone()
    loaded = json.loads(row[0]) if row else {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update({key: value for key, value in loaded.items() if key != "content_type_instructions"})
    merged["content_type_instructions"] = dict(DEFAULT_SETTINGS["content_type_instructions"])
    merged["content_type_instructions"].update(loaded.get("content_type_instructions", {}))
    return merged


def save_settings(conn, settings: dict) -> None:
    conn.execute("UPDATE prompt_settings SET settings_json=?,updated_at=? WHERE id=1", (json.dumps(settings, ensure_ascii=False), _now()))
    conn.commit()


def get_last_mode(conn) -> str:
    init_schema(conn)
    row = conn.execute("SELECT last_mode FROM prompt_settings WHERE id=1").fetchone()
    return row[0] if row and row[0] in {"Quick Prompt", "Advanced Prompt"} else "Quick Prompt"


def save_last_mode(conn, mode: str) -> None:
    conn.execute("UPDATE prompt_settings SET last_mode=?,updated_at=? WHERE id=1", (mode, _now()))
    conn.commit()


def reset_setting_section(settings: dict, key: str) -> dict:
    updated = json.loads(json.dumps(settings))
    if key.startswith("content_type:"):
        template_id = key.split(":", 1)[1]
        updated["content_type_instructions"][template_id] = DEFAULT_SETTINGS["content_type_instructions"].get(template_id, "")
    elif key in DEFAULT_SETTINGS:
        updated[key] = DEFAULT_SETTINGS[key]
    return updated


def validate_settings_import(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("The imported JSON must contain an object.")
    allowed = set(DEFAULT_SETTINGS)
    cleaned = {key: value[key] for key in allowed if key in value}
    for key, item in cleaned.items():
        if key == "content_type_instructions":
            if not isinstance(item, dict): raise ValueError("content_type_instructions must be an object.")
        elif not isinstance(item, str):
            raise ValueError(f"{key} must be text.")
    merged = dict(DEFAULT_SETTINGS)
    merged.update({key: item for key, item in cleaned.items() if key != "content_type_instructions"})
    merged["content_type_instructions"] = dict(DEFAULT_SETTINGS["content_type_instructions"])
    merged["content_type_instructions"].update(cleaned.get("content_type_instructions", {}))
    return merged


def list_presets(conn):
    init_schema(conn)
    return conn.execute("SELECT * FROM prompt_presets ORDER BY name COLLATE NOCASE,id").fetchall()


def save_preset(conn, name, content_type, configuration, selected_ids=None, preset_id=None):
    now = _now(); selected_ids = selected_ids or []
    if preset_id:
        conn.execute("UPDATE prompt_presets SET name=?,content_type=?,configuration_json=?,include_episodes=?,selected_episode_ids=?,updated_at=? WHERE id=?", (name,content_type,json.dumps(configuration,ensure_ascii=False),int(bool(selected_ids)),json.dumps(selected_ids),now,preset_id))
    else:
        conn.execute("INSERT INTO prompt_presets(name,content_type,configuration_json,include_episodes,selected_episode_ids,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (name,content_type,json.dumps(configuration,ensure_ascii=False),int(bool(selected_ids)),json.dumps(selected_ids),now,now))
    conn.commit()


def duplicate_preset(conn, preset_id):
    row = conn.execute("SELECT * FROM prompt_presets WHERE id=?", (preset_id,)).fetchone()
    if row: save_preset(conn, f"{row['name']} copy", row["content_type"], json.loads(row["configuration_json"]), json.loads(row["selected_episode_ids"]))


def delete_preset(conn, preset_id):
    conn.execute("DELETE FROM prompt_presets WHERE id=?", (preset_id,)); conn.commit()


def add_history(conn, content_type, topic, selected_ids, prompt, configuration):
    conn.execute("INSERT INTO prompt_history(created_at,content_type,topic,selected_episode_ids,generated_prompt,configuration_json) VALUES(?,?,?,?,?,?)", (_now(),content_type,topic,json.dumps(selected_ids),prompt,json.dumps(configuration,ensure_ascii=False)))
    conn.execute("DELETE FROM prompt_history WHERE id NOT IN (SELECT id FROM prompt_history ORDER BY id DESC LIMIT 50)")
    conn.commit()


def list_history(conn):
    init_schema(conn)
    return conn.execute("SELECT * FROM prompt_history ORDER BY id DESC LIMIT 50").fetchall()


def delete_history(conn, history_id):
    conn.execute("DELETE FROM prompt_history WHERE id=?", (history_id,)); conn.commit()


def clear_history(conn):
    conn.execute("DELETE FROM prompt_history"); conn.commit()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


SEMANTIC_EXPANSIONS = {
    "healthy relationship with food": ["food rules", "emotional eating", "restriction", "cheat meals", "food guilt", "sustainable eating", "all or nothing thinking"],
    "maintenance": ["fear of regain", "keeping weight off", "maintenance mindset", "sustainable habits"],
    "plateau": ["scale stopped moving", "weight loss plateau", "patience", "quitting"],
    "motivation": ["consistency", "discipline", "momentum", "reconnecting with your why"],
    "food addiction": ["food noise", "binge eating", "cravings", "loss of control around food"],
}


def expanded_terms(query: str) -> list[str]:
    q = normalize(query)
    terms = [q] + [token for token in q.split() if len(token) > 2]
    for trigger, values in SEMANTIC_EXPANSIONS.items():
        if trigger in q or q in trigger:
            terms.extend(normalize(item) for item in values)
    return list(dict.fromkeys(term for term in terms if term))


def relevant_excerpts(transcript: str, query: str, limit=3, context=650) -> list[str]:
    if not transcript: return []
    terms = expanded_terms(query)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", transcript) if len(part.strip()) >= 50]
    if not paragraphs: paragraphs = [transcript]
    scored = []
    for index, paragraph in enumerate(paragraphs):
        text = normalize(paragraph)
        score = sum((10 if term == normalize(query) else 2) * text.count(term) for term in terms)
        if score: scored.append((score, index, paragraph))
    if not scored:
        return [transcript[: min(len(transcript), context * 2)].strip()]
    selected = []
    for _, index, paragraph in sorted(scored, key=lambda item: (-item[0], item[1])):
        excerpt = paragraph[: context * 2].strip()
        if excerpt and excerpt not in selected: selected.append(excerpt)
        if len(selected) >= limit: break
    return selected


def _array(value) -> list:
    try: return json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError): return []


def load_episode_material(conn, episode_id: int, query: str, inclusion_mode: str, custom_selection="", include_quotes=True) -> dict:
    row = conn.execute("""
        SELECT e.*,
               COALESCE(NULLIF(x.main_category,''), e.main_category) AS workspace_main_category,
               x.central_question AS workspace_central_question,
               COALESCE(NULLIF(x.central_struggle,''), e.central_struggle) AS workspace_central_struggle,
               COALESCE(NULLIF(x.core_coaching_theme,''), e.core_coaching_theme) AS workspace_core_theme,
               x.primary_nick_framework, x.secondary_nick_frameworks, x.incidental_nick_concepts,
               x.simple_tags, x.emotional_themes, x.target_audience,
               x.topic_tags, x.search_queries, x.hidden_concepts, x.myths_debunked,
               x.key_takeaways, x.caller_questions
        FROM episodes e LEFT JOIN episode_enrichment x ON x.episode_id=e.id WHERE e.id=?
    """, (episode_id,)).fetchone()
    if not row: return {}
    arrays = {field: _array(row[field]) for field in ["secondary_nick_frameworks","incidental_nick_concepts","simple_tags","emotional_themes","target_audience","weight_loss_stage","topic_tags","search_queries","hidden_concepts","myths_debunked","key_takeaways","caller_questions"]}
    quotes = []
    if include_quotes:
        quotes = [dict(item) for item in conn.execute("SELECT quote,speaker,topic FROM quotes WHERE episode_id=? ORDER BY id", (episode_id,))]
    material = {
        "episode_id": row["episode_id"], "episode_number": row["episode_number"], "title": row["episode_title"],
        "publish_date": row["publish_date"], "youtube_url": row["youtube_url"],
        "main_category": row["workspace_main_category"], "central_question": row["workspace_central_question"],
        "summary": row["detailed_summary"] or row["short_summary"],
        "main_lesson": row["workspace_core_theme"] or row["nicks_main_advice"],
        "central_struggle": row["workspace_central_struggle"], "primary_framework": row["primary_nick_framework"],
        "secondary_frameworks": arrays["secondary_nick_frameworks"],
        "key_concepts": arrays["hidden_concepts"], "simple_tags": arrays["simple_tags"],
        "semantic_tags": arrays["topic_tags"], "supporting_stories": [], "supporting_quotes": quotes,
        "actionable_takeaways": arrays["key_takeaways"], "target_audience": arrays["target_audience"],
    }
    if inclusion_mode == "Database fields plus relevant transcript excerpts":
        material["relevant_transcript_excerpts"] = relevant_excerpts(row["transcript"], query)
    elif inclusion_mode == "Full transcript":
        material["full_transcript"] = row["transcript"]
    elif inclusion_mode == "Custom selection" and custom_selection.strip():
        material["custom_source_selection"] = custom_selection.strip()
    return material


def _clean_lines(value) -> str:
    return "\n".join(line.strip() for line in str(value or "").splitlines() if line.strip())


def _section(title, body):
    body = _clean_lines(body)
    return f"{title}\n{body}" if body else ""


def _material_text(material: dict) -> str:
    labels = [
        ("Episode", "episode_id"), ("Title", "title"), ("Publish date", "publish_date"), ("YouTube URL", "youtube_url"),
        ("Main category", "main_category"), ("Central question", "central_question"), ("Summary", "summary"),
        ("Main lesson", "main_lesson"), ("Central struggle", "central_struggle"), ("Primary Nick framework", "primary_framework"),
        ("Secondary Nick frameworks", "secondary_frameworks"), ("Key concepts", "key_concepts"), ("Simple tags", "simple_tags"),
        ("Semantic tags", "semantic_tags"), ("Target audience", "target_audience"), ("Actionable takeaways", "actionable_takeaways"),
        ("Supporting stories", "supporting_stories"), ("Supporting quotes", "supporting_quotes"),
        ("Relevant transcript excerpts", "relevant_transcript_excerpts"), ("Custom source selection", "custom_source_selection"),
        ("Full transcript", "full_transcript"),
    ]
    chunks = []
    for label, key in labels:
        value = material.get(key)
        if not value: continue
        if key == "supporting_quotes":
            text = "\n".join(f'“{item["quote"]}” — {item.get("speaker") or "Unknown speaker"}' for item in value if item.get("quote"))
        elif isinstance(value, list): text = "\n".join(f"- {item}" for item in value if item)
        else: text = str(value)
        if text.strip(): chunks.append(f"{label}:\n{text.strip()}")
    return "\n\n".join(chunks)


def assemble_prompt(settings: dict, template_id: str, config: dict, materials: list[dict]) -> str:
    template = TEMPLATES_BY_ID[template_id]
    user_lines = []
    config_labels = {
        "topic":"Topic or research question", "main_angle":"Main angle", "newsletter_angle":"Newsletter angle",
        "central_lesson":"Central lesson", "target_audience":"Target audience", "goal":"Goal", "length":"Desired length",
        "tone":"Tone", "cta":"CTA", "language":"Language", "number_of_options":"Number of options",
        "number_of_emails":"Number of emails", "email_goals":"Goal of each email", "sequence_cta":"Sequence CTA",
        "additional_instructions":"Additional instructions",
    }
    for key, label in config_labels.items():
        value = config.get(key)
        if value not in (None, "", []): user_lines.append(f"{label}: {value}")
    user_lines.append(f"Include episode references: {'Yes' if config.get('include_episode_references', True) else 'No'}")
    user_lines.append(f"Include supporting quotes: {'Yes' if config.get('include_supporting_quotes', True) else 'No'}")
    sections = [
        _section("ROLE AND PURPOSE", settings.get("master_prompt")),
        _section("SOURCE PRIORITY", settings.get("source_priority")),
        _section("RESEARCH RULES", settings.get("research_rules")),
        _section("WLHL VOICE", settings.get("nick_voice")),
        _section("WLHL PHILOSOPHY", settings.get("wlhl_philosophy")),
        _section("CONTENT RULES", settings.get("content_rules")),
        _section("LANGUAGE RULES", f"Language to avoid:\n{settings.get('forbidden_language','')}\n\nPreferred language:\n{settings.get('preferred_language','')}"),
        _section("CTA RULES", settings.get("cta_rules")),
        _section("FORMATTING RULES", settings.get("formatting_rules")),
        _section("CONTENT-TYPE INSTRUCTIONS", settings.get("content_type_instructions", {}).get(template_id) or template.default_instructions),
        _section("TASK", f"Create: {template.name}\n" + "\n".join(user_lines)),
        _section("SELECTED EPISODE MATERIAL", "\n\n---\n\n".join(_material_text(item) for item in materials if item)),
        _section("OUTPUT FORMAT", "\n".join(f"- {item}" for item in template.output_requirements)),
    ]
    if config.get("include_source_notes", True):
        sections.append(_section("SOURCE NOTES", "At the end, list the episodes actually used and identify which claims, stories, concepts, or exact quotes came from each. Clearly label summaries or adaptations. Do not present an adaptation as an exact quote."))
    return "\n\n".join(section for section in sections if section.strip()).strip()


def prompt_metrics(prompt: str) -> dict:
    words = len(re.findall(r"\b\w+\b", prompt or "")); characters = len(prompt or ""); tokens = round(characters / 4)
    size = "Small" if tokens < 2500 else "Moderate" if tokens < 7000 else "Large" if tokens < 16000 else "Very large"
    return {"words": words, "characters": characters, "tokens": tokens, "size": size}
