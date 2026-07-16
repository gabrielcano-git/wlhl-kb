from __future__ import annotations

import sqlite3
import html
import hashlib
import csv
import io
import json
import os
import re
import signal
import threading
import unicodedata
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from prompt_workspace_ui import render_prompt_workspace, render_writing_settings

ROOT = Path(__file__).resolve().parent
DB = ROOT / "database.sqlite"

st.set_page_config(page_title="WLHL Knowledge Base", page_icon="☎️", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{max-width:1240px;padding-top:5rem;padding-bottom:3rem}
.wlhl-title{font-size:2.15rem;font-weight:800;letter-spacing:-.04em;line-height:1.1}
.muted,.result-count{color:#64748b}.tag{display:inline-block;background:#e6f7f5;color:#075e59;border-radius:999px;padding:3px 9px;margin:2px;font-size:.82rem}
[data-testid="stMetric"]{background:#f8fafc;border:1px solid #e2e8f0;padding:15px;border-radius:14px;color:#000!important}
[data-testid="stMetric"] *{color:#000!important}
[data-testid="stTextInput"] input{font-size:1.08rem;padding:.78rem}.stButton button{border-radius:10px}
[data-testid="stSidebar"] [data-testid="stImage"] button{display:none!important}
mark{background:#fef08a;padding:0 2px}.section-space{height:.6rem}
@media(max-width:760px){.block-container{padding:4.25rem 1rem 2rem}.wlhl-title{font-size:1.75rem}[data-testid="stMetric"]{padding:10px}}
</style>""", unsafe_allow_html=True)

@st.cache_resource
def db():
    connection = sqlite3.connect(DB, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection

def scalar(sql, params=()):
    return db().execute(sql, params).fetchone()[0]

def term_values(episode_db_id, kind):
    return [r[0] for r in db().execute("SELECT value FROM episode_terms WHERE episode_id=? AND kind=? ORDER BY value", (episode_db_id, kind))]

ENRICHMENT_LISTS = {"secondary_nick_frameworks", "incidental_nick_concepts", "simple_tags", "emotional_themes", "target_audience", "weight_loss_stage", "topic_tags", "search_queries", "hidden_concepts", "myths_debunked", "key_takeaways", "caller_questions"}

def enrichment(episode_db_id):
    row = db().execute("SELECT * FROM episode_enrichment WHERE episode_id=?", (episode_db_id,)).fetchone()
    if not row: return {}
    data = dict(row)
    for field in ENRICHMENT_LISTS:
        try: data[field] = json.loads(data.get(field) or "[]")
        except json.JSONDecodeError: data[field] = []
    return data

def normalized(value):
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def row_value(row, key, default=""):
    if isinstance(row, dict): return row.get(key, default)
    return row[key] if key in row.keys() else default

def split_manual(value):
    return [item.strip() for item in (value or "").split(";") if item.strip()]

def export_database_csv():
    connection = db()
    headers = [
        "Episode ID", "Episode Number", "Episode Title", "Publish Date", "YouTube URL",
        "Transcript Filename", "Relative Transcript Path", "Episode Type", "Guest / Caller Name",
        "Main Category", "Central Question", "Central Struggle", "Core Coaching Theme",
        "Primary Nick Framework", "Secondary Nick Frameworks", "Incidental Nick Concepts",
        "Emotional Themes", "Target Audience", "Weight Loss Stage", "Simple Tags", "Topic Tags",
        "Search Queries", "Hidden Concepts", "Myths Debunked", "Key Takeaways", "Caller Questions",
        "Memorable Quotes", "Email Ideas", "Short Hooks", "Transcript",
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for episode in connection.execute("SELECT * FROM episodes ORDER BY episode_number,episode_title"):
        meta = enrichment(episode["id"])
        list_text = lambda field: "; ".join(str(value) for value in meta.get(field, []) if value)
        quotes = "\n".join(
            f"{item['quote']} — {item['speaker'] or 'Unknown speaker'}"
            for item in connection.execute("SELECT quote,speaker FROM quotes WHERE episode_id=? ORDER BY id", (episode["id"],))
        )
        email_ideas = "\n".join(
            " | ".join(part for part in [item["idea"], item["suggested_subject"], item["cta"]] if part)
            for item in connection.execute("SELECT idea,suggested_subject,cta FROM email_ideas WHERE episode_id=? ORDER BY id", (episode["id"],))
        )
        hooks = "\n".join(
            " | ".join(part for part in [item["hook"], item["exact_or_adapted"]] if part)
            for item in connection.execute("SELECT hook,exact_or_adapted FROM short_hooks WHERE episode_id=? ORDER BY id", (episode["id"],))
        )
        writer.writerow([
            episode["episode_id"], episode["episode_number"], episode["episode_title"], episode["publish_date"],
            episode["youtube_url"], episode["transcript_filename"], episode["relative_transcript_path"],
            meta.get("episode_type") or episode["episode_type"], episode["guest_caller_name"],
            meta.get("main_category") or episode["main_category"] or episode["main_topic"],
            meta.get("central_question", ""), meta.get("central_struggle") or episode["central_struggle"],
            meta.get("core_coaching_theme") or episode["core_coaching_theme"], meta.get("primary_nick_framework", ""),
            list_text("secondary_nick_frameworks"), list_text("incidental_nick_concepts"),
            list_text("emotional_themes"), list_text("target_audience"), list_text("weight_loss_stage"),
            list_text("simple_tags"), list_text("topic_tags"), list_text("search_queries"),
            list_text("hidden_concepts"), list_text("myths_debunked"), list_text("key_takeaways"),
            list_text("caller_questions"), quotes, email_ideas, hooks, episode["transcript"],
        ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")

def refresh_episode_search(episode_db_id):
    c=db(); row=c.execute("SELECT * FROM episodes WHERE id=?",(episode_db_id,)).fetchone()
    if not row: return
    terms={}
    for item in c.execute("SELECT kind,value FROM episode_terms WHERE episode_id=?",(episode_db_id,)): terms.setdefault(item["kind"],[]).append(item["value"])
    topics=" ".join(topic_values(episode_db_id)); quotes_text=" ".join(x[0] for x in c.execute("SELECT quote FROM quotes WHERE episode_id=?",(episode_db_id,)))
    c.execute("DELETE FROM episode_search WHERE episode_db_id=?",(episode_db_id,))
    c.execute("INSERT INTO episode_search VALUES(?,?,?,?,?,?,?,?,?,?,?)",(episode_db_id,row["episode_title"]," ".join([row["short_summary"] or "",row["detailed_summary"] or ""])," ".join(terms.get("key_takeaway",[])),row["nicks_main_advice"] or "",row["caller_problem"] or "",row["transcript"]," ".join(terms.get("keyword",[])+terms.get("search_term",[])+terms.get("hidden_concept",[])),quotes_text,topics,row["guest_caller_name"] or ""))
    c.commit()

def refresh_enrichment_search(episode_db_id):
    c=db(); row=c.execute("SELECT e.id,e.episode_title,e.transcript,x.* FROM episodes e JOIN episode_enrichment x ON x.episode_id=e.id WHERE e.id=?",(episode_db_id,)).fetchone()
    c.execute("DELETE FROM enrichment_search WHERE episode_db_id=?",(episode_db_id,))
    if row:
        unpack=lambda field:" ".join(json.loads(row[field] or "[]"))
        simple=unpack("simple_tags");topic=" ".join([row["main_category"] or "",unpack("topic_tags")]);semantic=" ".join([row["central_question"] or "",row["central_struggle"] or "",row["core_coaching_theme"] or "",row["primary_nick_framework"] or "",unpack("secondary_nick_frameworks"),unpack("incidental_nick_concepts"),unpack("emotional_themes"),unpack("target_audience"),unpack("weight_loss_stage"),unpack("search_queries"),unpack("hidden_concepts"),unpack("myths_debunked"),unpack("key_takeaways"),unpack("caller_questions")])
        c.execute("INSERT INTO enrichment_search VALUES(?,?,?,?,?,?)",(episode_db_id,row["episode_title"],simple,topic,semantic,row["transcript"]))
    c.commit()

def save_manual_episode(values):
    c=db(); number=values["episode_number"]; episode_id=f"EP-{number:03d}"
    if c.execute("SELECT 1 FROM episodes WHERE episode_number=?",(number,)).fetchone(): raise ValueError(f"{episode_id} already exists")
    if c.execute("SELECT 1 FROM episodes WHERE transcript_filename=?",(values["transcript_filename"],)).fetchone(): raise ValueError("That transcript filename already exists")
    transcript=values["transcript"]
    now=datetime.now().isoformat(timespec="seconds")
    columns=["episode_id","episode_number","episode_title","publish_date","youtube_url","transcript_filename","relative_transcript_path","episode_type","guest_caller_name","main_topic","main_category","short_summary","detailed_summary","nicks_main_advice","caller_problem","resolution","weight_loss_stage","cta_recommendation","transcript_status","review_notes","central_struggle","core_coaching_theme","success_story","transcript","source_hash","source_mtime","processed_at"]
    row=[episode_id,number,values["episode_title"],str(values["publish_date"]),values["youtube_url"],values["transcript_filename"],f"transcripts/{values['transcript_filename']}",values["episode_type"],values["caller"],values["main_category"],values["main_category"],"","","","","","","","Manual Entry",json.dumps(["Created manually in the WLHL app"]),values["central_struggle"],values["core_coaching_theme"],int(values["success_story"]),transcript,hashlib.sha256(transcript.encode()).hexdigest(),0,now]
    placeholders=",".join("?" for _ in columns); cur=c.execute(f"INSERT INTO episodes({','.join(columns)}) VALUES({placeholders})",row); eid=cur.lastrowid
    list_fields=["secondary_nick_frameworks","incidental_nick_concepts","simple_tags","emotional_themes","target_audience","weight_loss_stage","topic_tags","search_queries","hidden_concepts","myths_debunked","key_takeaways"]
    payload={field:json.dumps(split_manual(values.get(field,"")),ensure_ascii=False) for field in list_fields}
    ecols=["episode_id","source_episode_number","source_episode_title","episode_type","main_category","central_question","central_struggle","core_coaching_theme","primary_nick_framework",*list_fields,"source_filename","source_hash","imported_at"]
    erow=[eid,episode_id,values["episode_title"],values["episode_type"],values["main_category"],values["central_question"],values["central_struggle"],values["core_coaching_theme"],values["primary_nick_framework"],*[payload[x] for x in list_fields],"Manual app entry",hashlib.sha256(json.dumps(values,default=str).encode()).hexdigest(),now]
    c.execute(f"INSERT INTO episode_enrichment({','.join(ecols)}) VALUES({','.join('?' for _ in ecols)})",erow)
    for field in list_fields:
        for item in json.loads(payload[field]): c.execute("INSERT OR IGNORE INTO enrichment_values VALUES(?,?,?,?)",(eid,field,item,normalized(item)))
    c.commit();refresh_episode_search(eid);refresh_enrichment_search(eid);return eid

def topic_values(episode_db_id):
    return [r[0] for r in db().execute("SELECT t.name FROM episode_topics et JOIN topics t ON t.id=et.topic_id WHERE et.episode_id=? ORDER BY et.is_primary DESC,t.name", (episode_db_id,))]

def tag_line(values):
    if values:
        st.markdown("".join(f'<span class="tag">{html.escape(str(v))}</span>' for v in values if v), unsafe_allow_html=True)

def open_episode(episode_db_id):
    st.session_state.episode_id = episode_db_id

def close_open_episode():
    st.session_state.pop("episode_id", None)

def request_app_stop():
    st.session_state.confirm_app_stop = True

def cancel_app_stop():
    st.session_state.confirm_app_stop = False

def stop_local_app():
    st.session_state.confirm_app_stop = False
    st.session_state._stop_message = True
    threading.Timer(1.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

def go_to_add_episode():
    close_open_episode()
    st.session_state.navigation = "Add Episode"

def episode_list_button(row, prefix):
    st.button(f"{row['episode_id']} — {row['episode_title']}", key=f"{prefix}-{row['id']}", on_click=open_episode, args=(row["id"],), use_container_width=True)

def result_card(row, key_prefix="result"):
    enriched = enrichment(row["id"])
    with st.container(border=True):
        st.subheader(f"{row['episode_id']} · {row['episode_title']}")
        category = enriched.get("main_category") or row_value(row, "main_category") or row_value(row, "main_topic")
        episode_type = enriched.get("episode_type") or row_value(row, "episode_type")
        st.caption(" · ".join(x for x in [row["publish_date"], episode_type, category] if x))
        explanation = row_value(row, "match_explanation")
        if explanation:
            st.markdown(f"**Why it matched:** {html.escape(explanation)}")
        if row_value(row, "snippet"):
            st.markdown(row_value(row, "snippet"), unsafe_allow_html=True)
        elif row["short_summary"]:
            st.write(row["short_summary"])
        tags = (enriched.get("simple_tags") or [])[:3] + (enriched.get("topic_tags") or topic_values(row["id"]))[:3]
        tag_line(list(dict.fromkeys(tags))[:6])
        youtube_action,open_action,spacer = st.columns([1.4,1.2,5.4])
        if row["youtube_url"]: youtube_action.link_button("▶ YouTube", row["youtube_url"], use_container_width=True)
        open_action.button("Open →", key=f"{key_prefix}-{row['id']}", on_click=open_episode, args=(row["id"],), use_container_width=True)

def render_edit_content(episode_db_id):
    c=db()
    with st.expander("✏️ Edit Content — Quotes, Email Ideas & Short Hooks"):
        st.caption("Changes are saved directly to the local WLHL database.")
        quote_tab,email_tab,hook_tab=st.tabs(["Memorable Quotes","Email Ideas","Short Hooks"])
        with quote_tab:
            for item in c.execute("SELECT * FROM quotes WHERE episode_id=? ORDER BY id",(episode_db_id,)).fetchall():
                with st.form(f"edit-quote-{item['id']}"):
                    quote=st.text_area("Quote",item["quote"] or "",key=f"q-{item['id']}");a,b=st.columns(2);speaker=a.text_input("Speaker",item["speaker"] or "",key=f"qs-{item['id']}");topic=b.text_input("Topic",item["topic"] or "",key=f"qt-{item['id']}");u,d=st.columns(2)
                    if u.form_submit_button("Save changes",use_container_width=True): c.execute("UPDATE quotes SET quote=?,speaker=?,topic=? WHERE id=?",(quote.strip(),speaker.strip(),topic.strip(),item["id"]));c.commit();refresh_episode_search(episode_db_id);st.rerun()
                    if d.form_submit_button("Delete",use_container_width=True): c.execute("DELETE FROM quotes WHERE id=?",(item["id"],));c.commit();refresh_episode_search(episode_db_id);st.rerun()
            with st.form(f"add-quote-{episode_db_id}"):
                st.markdown("**Add a quote**");quote=st.text_area("New quote",key=f"nq-{episode_db_id}");a,b=st.columns(2);speaker=a.text_input("Speaker",key=f"nqs-{episode_db_id}");topic=b.text_input("Topic",key=f"nqt-{episode_db_id}")
                if st.form_submit_button("Add quote",use_container_width=True):
                    if quote.strip(): c.execute("INSERT INTO quotes(episode_id,quote,speaker,topic) VALUES(?,?,?,?)",(episode_db_id,quote.strip(),speaker.strip(),topic.strip()));c.commit();refresh_episode_search(episode_db_id);st.rerun()
        with email_tab:
            for item in c.execute("SELECT * FROM email_ideas WHERE episode_id=? ORDER BY id",(episode_db_id,)).fetchall():
                with st.form(f"edit-email-{item['id']}"):
                    idea=st.text_area("Email idea",item["idea"] or "",key=f"ei-{item['id']}");topic=st.text_input("Topic",item["topic"] or "",key=f"eit-{item['id']}");subject=st.text_input("Suggested subject",item["suggested_subject"] or "",key=f"eis-{item['id']}");cta=st.text_input("CTA",item["cta"] or "",key=f"eic-{item['id']}");u,d=st.columns(2)
                    if u.form_submit_button("Save changes",use_container_width=True): c.execute("UPDATE email_ideas SET topic=?,idea=?,suggested_subject=?,cta=? WHERE id=?",(topic.strip(),idea.strip(),subject.strip(),cta.strip(),item["id"]));c.commit();st.rerun()
                    if d.form_submit_button("Delete",use_container_width=True): c.execute("DELETE FROM email_ideas WHERE id=?",(item["id"],));c.commit();st.rerun()
            with st.form(f"add-email-{episode_db_id}"):
                st.markdown("**Add an email idea**");idea=st.text_area("New email idea",key=f"nei-{episode_db_id}");topic=st.text_input("Topic",key=f"neit-{episode_db_id}");subject=st.text_input("Suggested subject",key=f"neis-{episode_db_id}");cta=st.text_input("CTA",key=f"neic-{episode_db_id}")
                if st.form_submit_button("Add email idea",use_container_width=True):
                    if idea.strip(): c.execute("INSERT INTO email_ideas(episode_id,topic,idea,suggested_subject,cta) VALUES(?,?,?,?,?)",(episode_db_id,topic.strip(),idea.strip(),subject.strip(),cta.strip()));c.commit();st.rerun()
        with hook_tab:
            for item in c.execute("SELECT * FROM short_hooks WHERE episode_id=? ORDER BY id",(episode_db_id,)).fetchall():
                with st.form(f"edit-hook-{item['id']}"):
                    hook=st.text_area("Hook",item["hook"] or "",key=f"h-{item['id']}");topic=st.text_input("Topic",item["topic"] or "",key=f"ht-{item['id']}");kind=st.selectbox("Type",["Exact Quote","Adapted"],index=0 if item["exact_or_adapted"]=="Exact Quote" else 1,key=f"hk-{item['id']}");u,d=st.columns(2)
                    if u.form_submit_button("Save changes",use_container_width=True): c.execute("UPDATE short_hooks SET topic=?,hook=?,exact_or_adapted=? WHERE id=?",(topic.strip(),hook.strip(),kind,item["id"]));c.commit();st.rerun()
                    if d.form_submit_button("Delete",use_container_width=True): c.execute("DELETE FROM short_hooks WHERE id=?",(item["id"],));c.commit();st.rerun()
            with st.form(f"add-hook-{episode_db_id}"):
                st.markdown("**Add a short hook**");hook=st.text_area("New hook",key=f"nh-{episode_db_id}");topic=st.text_input("Topic",key=f"nht-{episode_db_id}");kind=st.selectbox("Type",["Exact Quote","Adapted"],key=f"nhk-{episode_db_id}")
                if st.form_submit_button("Add short hook",use_container_width=True):
                    if hook.strip(): c.execute("INSERT INTO short_hooks(episode_id,topic,hook,exact_or_adapted) VALUES(?,?,?,?)",(episode_db_id,topic.strip(),hook.strip(),kind));c.commit();st.rerun()

def episode_dialog():
    if "episode_id" not in st.session_state:
        return
    row = db().execute("SELECT * FROM episodes WHERE id=?", (st.session_state.episode_id,)).fetchone()
    if not row:
        del st.session_state.episode_id
        return

    @st.dialog(f"{row['episode_id']} · {row['episode_title']}", width="large")
    def show():
        enriched = enrichment(row["id"])
        display_type = enriched.get("episode_type") or row["episode_type"]
        st.caption(" · ".join(x for x in [row["publish_date"], display_type, row["guest_caller_name"]] if x))
        if row["youtube_url"]:
            st.link_button("▶ Watch on YouTube", row["youtube_url"])
        st.subheader("Summary")
        key_takeaways = enriched.get("key_takeaways", [])
        if key_takeaways:
            for item in key_takeaways:
                st.markdown(f"- {item}")
        else:
            st.caption("No Key Takeaways were provided in the source spreadsheet for this episode.")
        if enriched:
            st.divider(); st.subheader("Episode analysis")
            st.markdown("#### Overview")
            for label, field in [("Main Category","main_category"),("Central Question","central_question"),("Central Struggle","central_struggle"),("Core Coaching Theme","core_coaching_theme")]:
                if enriched.get(field): st.markdown(f"**{label}**  \n{enriched[field]}")
            st.markdown("#### WLHL Concepts")
            if enriched.get("primary_nick_framework"): st.markdown(f"**Primary Nick Framework**  \n{enriched['primary_nick_framework']}")
            for label, field in [("Secondary Nick Frameworks","secondary_nick_frameworks"),("Incidental Nick Concepts","incidental_nick_concepts")]:
                if enriched.get(field): st.markdown(f"**{label}**"); tag_line(enriched[field])
            st.markdown("#### Discovery")
            for label, field in [("Simple Tags","simple_tags"),("Topic Tags","topic_tags"),("Search Queries","search_queries"),("Target Audience","target_audience"),("Weight Loss Stage","weight_loss_stage")]:
                if enriched.get(field): st.markdown(f"**{label}**"); tag_line(enriched[field])
            st.markdown("#### Deeper Analysis")
            for label, field in [("Emotional Themes","emotional_themes"),("Hidden Concepts","hidden_concepts"),("Myths Debunked","myths_debunked")]:
                if enriched.get(field):
                    st.markdown(f"**{label}**")
                    for item in enriched[field]: st.markdown(f"- {item}")
            if enriched.get("caller_questions"):
                st.markdown("**Caller's Questions**")
                for item in enriched["caller_questions"]: st.markdown(f"- {item}")
        else:
            st.markdown("**Main topic**"); tag_line([row["main_topic"]] if row["main_topic"] else [])
            st.markdown("**Secondary topics**"); tag_line(term_values(row["id"], "secondary_topic"))
            st.markdown("**Search terms and keywords**"); tag_line(term_values(row["id"], "search_term") + term_values(row["id"], "keyword"))
        details = [("Caller", row["guest_caller_name"]), ("Caller problem", row["caller_problem"]),
                   ("Nick's advice", row["nicks_main_advice"]), ("Resolution", row["resolution"]),
                   ("Core coaching theme", row["core_coaching_theme"]), ("CTA idea", row["cta_recommendation"])]
        for label, value in details:
            if value:
                st.markdown(f"**{label}**  \n{value}")
        quotes = db().execute("SELECT quote,speaker,topic FROM quotes WHERE episode_id=? ORDER BY id", (row["id"],)).fetchall()
        ideas = db().execute("SELECT idea,suggested_subject,cta FROM email_ideas WHERE episode_id=? ORDER BY id", (row["id"],)).fetchall()
        hooks = db().execute("SELECT hook,exact_or_adapted FROM short_hooks WHERE episode_id=? ORDER BY id", (row["id"],)).fetchall()
        with st.expander(f"Memorable quotes ({len(quotes)})"):
            for q in quotes: st.write(f'“{q["quote"]}” — {q["speaker"] or "Unknown speaker"}')
        with st.expander(f"Email ideas ({len(ideas)})"):
            for i in ideas: st.write(f'**{i["suggested_subject"] or "Email idea"}**  \n{i["idea"]}  \nCTA: {i["cta"] or "—"}')
        with st.expander(f"Short hooks ({len(hooks)})"):
            for h in hooks: st.write(f'{h["hook"]} · {h["exact_or_adapted"] or "Unspecified"}')
        render_edit_content(row["id"])
        st.divider()
        st.subheader("Full transcript")
        st.text_area("Transcript", row["transcript"], height=520, label_visibility="collapsed")
        if st.button("Close", use_container_width=True):
            del st.session_state.episode_id
            st.rerun()
    show()

STOP_WORDS = {"a","about","after","am","an","and","are","do","does","eat","episode","episodes","find","for","how","i","in","is","it","ll","me","my","of","on","show","the","to","video","videos","what","where","why","with"}
CONTEXT_WORDS = {"call","called","calling","go","going","nick","out","podcast","talk","talked","talking","weight","loss"}
QUERY_SYNONYMS = {
    "dinner": ["dining", "restaurant", "restaurants", "eat out", "eating out", "meal"],
    "friend": ["friends", "friendship", "friendships", "social", "socializing"],
    "friends": ["friend", "friendship", "friendships", "social", "socializing"],
    "doctor": ["medical", "physician"],
    "workout": ["exercise", "training", "gym"],
    "workouts": ["exercise", "training", "gym"],
    "hungry": ["hunger", "appetite"],
    "sad": ["sadness", "depression", "emotional"],
    "vacation": ["travel", "traveling", "holiday"],
    "weekend": ["weekends", "saturday", "sunday"],
}
SEMANTIC_RULES = [
    ({"grief eating","grief","bereavement"}, ["grief","sadness","emotional distress","emotional eating","coping with loss","bereavement"]),
    ({"starting over","start over","restarting","monday"}, ["restarting every monday","all or nothing thinking","quitting","weight regain","last day 1"]),
    ({"gain it back","gaining the weight back","keep the weight off","fear of regain"}, ["fear of regain","maintenance","sustainable weight loss","weight regain","keeping weight off"]),
    ({"food controls me","food control","food controls"}, ["food noise","emotional eating","binge eating","cravings","relationship with food"]),
    ({"lost motivation","motivation","momentum"}, ["motivation","complacency","consistency","momentum","plateau","reconnecting with your why"]),
    ({"bariatric","weight loss surgery"}, ["bariatric surgery","gastric bypass","weight loss surgery","post bariatric maintenance"]),
    ({"pizza","moderation"}, ["pizza","moderation","one slice","restaurant eating","food freedom"]),
]

def query_groups_are_nearby(text, groups, max_gap=700):
    """Return True when every query concept appears in one reasonably small passage."""
    if len(groups) < 2:
        return False
    events=[]
    for group_index, group in enumerate(groups):
        positions=[]
        for term in group:
            start=0
            while len(positions)<30:
                pos=text.find(term,start)
                if pos<0: break
                positions.append(pos); start=pos+max(1,len(term))
        events.extend((pos,group_index) for pos in positions)
    events.sort()
    counts={}; left=0
    for right,(position,group_index) in enumerate(events):
        counts[group_index]=counts.get(group_index,0)+1
        while len(counts)==len(groups):
            if position-events[left][0] <= max_gap: return True
            left_group=events[left][1]; counts[left_group]-=1
            if counts[left_group]==0: del counts[left_group]
            left+=1
    return False

def search_episodes(query, filters):
    rows = db().execute("SELECT e.* FROM episodes e ORDER BY e.episode_number").fetchall()
    q = normalized(query); tokens = [x for x in q.split() if x not in STOP_WORDS]
    focus_tokens = [token for token in tokens if token not in CONTEXT_WORDS]
    query_groups = []
    literal_query_groups = []
    for token in focus_tokens:
        variants = [token]
        if token.endswith("ies") and len(token)>4: variants.append(token[:-3]+"y")
        elif token.endswith("s") and len(token)>3: variants.append(token[:-1])
        literal_query_groups.append(list(dict.fromkeys(normalized(value) for value in variants if value)))
        variants.extend(QUERY_SYNONYMS.get(token, []))
        query_groups.append(list(dict.fromkeys(normalized(value) for value in variants if value)))
    concepts = list(tokens)
    for triggers, expansions in SEMANTIC_RULES:
        if any(trigger in q for trigger in triggers): concepts.extend(normalized(x) for x in expansions)
    concepts = list(dict.fromkeys(x for x in concepts if x))
    results=[]
    for source in rows:
        row=dict(source); meta=enrichment(row["id"])
        effective_type=meta.get("episode_type") or row["episode_type"]
        stages=meta.get("weight_loss_stage") or ([row["weight_loss_stage"]] if row["weight_loss_stage"] else [])
        topics=meta.get("topic_tags") or topic_values(row["id"])
        category=meta.get("main_category") or row["main_category"] or row["main_topic"] or ""
        type_filter = normalized(filters["type"])
        topic_filter = normalized(filters["topic"])
        stage_filter = normalized(filters["stage"])
        if type_filter and type_filter not in normalized(effective_type): continue
        if stage_filter and not any(stage_filter in normalized(stage) for stage in stages): continue
        if topic_filter and topic_filter not in normalized(" ".join([category, *topics])): continue
        if filters["success"] and not row["success_story"]: continue
        if filters["start"] and row["publish_date"]<str(filters["start"]): continue
        if filters["end"] and row["publish_date"]>str(filters["end"]): continue
        if not q: row["snippet"]=""; results.append(row); continue
        title=normalized(row["episode_title"]); simple=[normalized(x) for x in meta.get("simple_tags",[])]; topic_text=normalized(" ".join([category]+topics))
        semantic_fields=[("Episode Type",effective_type or ""),("Guest or Caller",row.get("guest_caller_name") or ""),("Central Question",meta.get("central_question","")),("Central Struggle",meta.get("central_struggle","")),("Core Coaching Theme",meta.get("core_coaching_theme","")),("Search Queries","; ".join(meta.get("search_queries",[]))),("Hidden Concepts","; ".join(meta.get("hidden_concepts",[]))),("Key Takeaways","; ".join(meta.get("key_takeaways",[]))),("Caller's Questions","; ".join(meta.get("caller_questions",[]))),("Nick Frameworks","; ".join([meta.get("primary_nick_framework","")]+meta.get("secondary_nick_frameworks",[])+meta.get("incidental_nick_concepts",[]))),("Emotional Themes","; ".join(meta.get("emotional_themes",[]))),("Target Audience","; ".join(meta.get("target_audience",[])))]
        semantic=normalized(" ".join(value for _,value in semantic_fields)); transcript=normalized(row["transcript"])
        metadata_text = " ".join([title, " ".join(simple), topic_text, semantic])
        searchable_text = " ".join([metadata_text, transcript])
        if query_groups and not any(any(term in searchable_text for term in group) for group in query_groups):
            continue
        if not focus_tokens and "call" in tokens and "call" not in normalized(effective_type):
            continue
        score=0; reason=""; snippet=""
        exact_transcript_match = len(q) > 2 and q in transcript
        metadata_group_hits = sum(any(term in metadata_text for term in group) for group in query_groups)
        transcript_group_hits = sum(any(term in transcript for term in group) for group in query_groups)
        group_count = len(query_groups)
        nearby_transcript_match = query_groups_are_nearby(transcript, literal_query_groups)
        natural_language_match = bool(group_count and (
            metadata_group_hits == group_count or nearby_transcript_match
        ))
        score += 130*metadata_group_hits + 25*transcript_group_hits
        if group_count and metadata_group_hits == group_count: score += 350
        elif nearby_transcript_match: score += 250
        elif group_count and transcript_group_hits == group_count: score += 100
        if q==title: score+=1200; reason="Exact episode title"
        elif q in title: score+=700; reason="Episode title"
        score+=80*sum(token in title for token in tokens)
        exact_simple=[raw for raw in meta.get("simple_tags",[]) if normalized(raw)==q]
        partial_simple=[]
        for raw in meta.get("simple_tags",[]):
            tag=normalized(raw)
            if q in tag or (len(tokens)==1 and tokens[0] in tag) or (len(tokens)>1 and all(token in tag for token in tokens)):
                partial_simple.append(raw)
        if exact_simple: score+=550; reason=f"Exact Simple Tag: {exact_simple[0]}"
        elif partial_simple: score+=320+40*min(len(partial_simple),3); reason=f"Simple Tag: {partial_simple[0]}"
        if q==normalized(category) or any(q==normalized(x) for x in topics): score+=300; reason=reason or f"Central topic: {category}"
        elif any(concept==normalized(category) for concept in concepts): score+=220; reason=reason or f"Main Category: {category}"
        topic_hits=sum(concept in topic_text for concept in concepts); score+=70*min(topic_hits,6)
        direct_semantic_hits=sum(token in semantic for token in tokens)
        semantic_hits=sum(concept in semantic for concept in concepts)
        score+=80*min(direct_semantic_hits,5)+25*min(max(0,semantic_hits-direct_semantic_hits),8)
        if len(q)>3 and q in semantic: score+=450; reason=reason or "Exact phrase in episode analysis"
        if semantic_hits and not reason:
            for label,value in semantic_fields:
                if any(concept in normalized(value) for concept in concepts): reason=f"{label} match"; snippet=html.escape(value[:360]); break
        transcript_hits=sum(transcript.count(token) for token in tokens)
        distinctive_transcript_hits=sum(1 for token in tokens if len(token)>=4 and token in transcript)
        score+=min(transcript_hits,12)+35*distinctive_transcript_hits
        if exact_transcript_match:
            score += 500
            reason = reason or "Exact phrase in transcript"
            pos = transcript.find(q)
            original = row["transcript"]
            snippet = html.escape(original[max(0,pos-140):pos+360].replace("\n"," "))
        elif transcript_hits and not reason:
            reason="Transcript match"
            positions=[transcript.find(token) for token in tokens if transcript.find(token)>=0]; pos=min(positions) if positions else 0
            original=row["transcript"]; snippet=html.escape(original[max(0,pos-90):pos+260].replace("\n"," "))
        if score>0:
            row["match_score"]=score; row["match_explanation"]=reason or "Natural-language concept match"; row["snippet"]=snippet; row["exact_transcript_match"]=exact_transcript_match; row["natural_language_match"]=natural_language_match; results.append(row)
    ranked = sorted(results,key=lambda x:(-x.get("match_score",0),x["episode_number"],x["episode_title"]))
    if q and ranked and not (not focus_tokens and "call" in tokens):
        strongest = ranked[0].get("match_score", 0)
        relevance_floor = max(20, strongest * 0.50)
        ranked = [row for row in ranked if row.get("match_score", 0) >= relevance_floor or row.get("exact_transcript_match")]
    return ranked

INTENT_WORDS = {"about","all","any","did","discuss","discussed","episode","episodes","find","i","in","mention","mentioned","me","my","of","on","show","talk","talked","talking","the","video","videos","where"}
CALL_IN_EPISODE_NUMBERS = (96, 97, 98, 99, 101, 103, 105, 110, 112, 115)

def all_episode_groups(query):
    raw = normalized(query)
    tokens = [token for token in raw.split() if token not in INTENT_WORDS]
    focus = " ".join(tokens).strip() or raw
    if not focus: return "", [], []
    main, mentioned, labels = [], [], []
    for source in db().execute("SELECT * FROM episodes ORDER BY episode_number"):
        row = dict(source); meta = enrichment(row["id"])
        primary_values = [row["episode_title"], meta.get("main_category", ""), meta.get("central_question", ""), meta.get("central_struggle", ""), meta.get("core_coaching_theme", "")]
        secondary_values = [meta.get("primary_nick_framework", "")] + meta.get("secondary_nick_frameworks", []) + meta.get("incidental_nick_concepts", [])
        secondary_values += meta.get("simple_tags", []) + meta.get("topic_tags", []) + meta.get("search_queries", []) + meta.get("hidden_concepts", []) + meta.get("emotional_themes", []) + meta.get("caller_questions", [])
        secondary_values += [meta.get("central_question", ""), meta.get("central_struggle", ""), meta.get("core_coaching_theme", ""), row["transcript"]]
        primary_text = normalized(" ".join(value for value in primary_values if value))
        secondary_text = normalized(" ".join(value for value in secondary_values if value))
        phrase_is_primary = focus in primary_text
        tokens_are_primary = len(tokens) > 1 and all(token in primary_text for token in tokens)
        if phrase_is_primary or tokens_are_primary:
            main.append(row)
            exact = next((value for value in primary_values if normalized(value) == focus), "")
            if exact: labels.append(exact)
        elif focus in secondary_text or (tokens and all(token in secondary_text for token in tokens)):
            mentioned.append(row)
            exact = next((value for value in secondary_values if normalized(value) == focus), "")
            if exact: labels.append(exact)
    label = labels[0] if labels else " ".join(word.capitalize() for word in focus.split())
    return label, main, mentioned

st.sidebar.image(str(ROOT / "assets" / "wlhl-logo.png"), width=220)
page = st.sidebar.radio(
    "Explore",
    ["All Episodes", "Prompt Workspace", "Search", "Add Episode", "Topics", "Call-In Episodes", "Writing Settings"],
    key="navigation",
    on_change=close_open_episode,
)
st.sidebar.caption("Everything stays on this computer.")
st.sidebar.divider()
st.sidebar.button("⏹ Stop App", on_click=request_app_stop, use_container_width=True)
if st.session_state.get("confirm_app_stop"):
    st.sidebar.warning("Stop the WLHL Knowledge Base now?")
    stop_yes, stop_no = st.sidebar.columns(2)
    stop_yes.button("Yes, stop", type="primary", on_click=stop_local_app, use_container_width=True)
    stop_no.button("Cancel", on_click=cancel_app_stop, use_container_width=True)
if st.session_state.get("confirm_app_stop") is False and st.session_state.get("_stop_message"):
    st.sidebar.success("App stopped. You can close this browser tab.")
st.markdown('<div class="wlhl-title">The Weight Loss Hotline</div><div class="muted">Search every episode, transcript, and coaching concept.</div>', unsafe_allow_html=True)
st.write("")
c = db()

if page == "Prompt Workspace":
    render_prompt_workspace(c, search_episodes, enrichment, open_episode)

elif page == "Writing Settings":
    render_writing_settings(c)

elif page == "Search":
    counts = [scalar("SELECT COUNT(*) FROM episodes"), scalar("SELECT COUNT(DISTINCT value) FROM (SELECT main_category value FROM episode_enrichment WHERE main_category<>'' UNION ALL SELECT value FROM enrichment_values WHERE kind='topic_tags')"),
              scalar("SELECT COUNT(*) FROM episodes WHERE episode_number IN (96,97,98,99,101,103,105,110,112,115)")]
    for col, label, value in zip(st.columns(3), ["Episodes", "Topics", "Call-In episodes"], counts):
        col.metric(label, value)
    st.write("")
    query = st.text_input("Search the knowledge base", placeholder="Search plateau, emotional eating, identity, maintenance, a caller problem, or an exact phrase…", label_visibility="collapsed")
    st.caption('Use natural keywords together, for example: “Gabby call-in episode” or “Nick talks about maintenance after weight loss.”')
    filters = {"type":"", "topic":"", "stage":"", "success":False, "start":None, "end":None}
    active = bool(query.strip())
    if active:
        rows = search_episodes(query, filters)
        st.markdown(f'<div class="result-count">{len(rows)} episode(s) found</div>', unsafe_allow_html=True)
        for row in rows: result_card(row)
    else:
        left,right = st.columns([1,1])
        with left:
            st.subheader("Recently added")
            for row in c.execute("SELECT * FROM episodes ORDER BY publish_date DESC,episode_number DESC LIMIT 6"):
                result_card(row, "recent")
        with right:
            st.subheader("Most common topics")
            common = c.execute("SELECT value name,COUNT(DISTINCT episode_id) n FROM (SELECT episode_id,main_category value FROM episode_enrichment WHERE main_category<>'' UNION ALL SELECT episode_id,value FROM enrichment_values WHERE kind='topic_tags') GROUP BY value ORDER BY n DESC,value LIMIT 12").fetchall()
            for row in common:
                st.write(f"**{row['name']}** · {row['n']} episodes")

elif page == "All Episodes":
    heading,add_action,export_action=st.columns([4,1.5,1.7]);heading.subheader("All Episodes");add_action.button("＋ Add New Episode",on_click=go_to_add_episode,use_container_width=True,type="primary")
    export_action.download_button(
        "⬇ Export Database",
        data=export_database_csv(),
        file_name=f"WLHL_Episode_Database_{date.today().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.caption("Browse every episode or search by a topic, framework, idea, or natural-language question.")
    all_query = st.text_input("Search all episodes", placeholder='Try: "videos where I talked about the Common Sense Diet"', label_visibility="collapsed")
    if all_query.strip():
        label, main_rows, mentioned_rows = all_episode_groups(all_query)
        st.markdown(f"### Main topic is {html.escape(label)}")
        st.caption(f"{len(main_rows)} episode(s) where this is a central focus")
        if not main_rows: st.info("No episodes were classified with this as a main topic.")
        for row in main_rows: episode_list_button(row, "all-main")
        st.divider()
        st.markdown(f"### {html.escape(label)} is mentioned")
        st.caption(f"{len(mentioned_rows)} additional episode(s) where this appears but is not the main focus")
        if not mentioned_rows: st.info("No additional mentions found.")
        for row in mentioned_rows: episode_list_button(row, "all-mentioned")
    else:
        rows = c.execute("SELECT * FROM episodes ORDER BY episode_number,episode_title").fetchall()
        st.caption(f"{len(rows)} episodes")
        left, right = st.columns(2)
        for index, row in enumerate(rows):
            with (left if index % 2 == 0 else right): episode_list_button(row, "all")

elif page == "Add Episode":
    st.subheader("Add Episode")
    st.caption("Create a new episode manually. No AI service is used and no existing transcript file is changed.")
    with st.form("add-episode-form"):
        a,b=st.columns(2);number=a.number_input("Episode number",min_value=1,step=1,value=max(1,scalar("SELECT MAX(episode_number) FROM episodes")+1));title=b.text_input("Episode title")
        a,b,c1=st.columns(3);publish_date=a.date_input("Publish date",value=date.today());episode_type=b.selectbox("Episode type",["Solo","Call-In","Interview","Live","Success Story","Q&A","Unknown"]);success_story=c1.checkbox("Success story")
        youtube_url=st.text_input("YouTube URL");caller=st.text_input("Guest / Caller name (leave blank if unknown)")
        uploaded=st.file_uploader("Upload transcript (.txt)",type=["txt"]);filename=st.text_input("Transcript filename",help="Use the exact canonical filename. If you upload a file, its filename is used automatically.")
        transcript=st.text_area("Or paste the full transcript",height=260)
        st.markdown("### Manual episode analysis")
        main_category=st.text_input("Main Category");central_question=st.text_area("Central Question");central_struggle=st.text_area("Central Struggle");core_theme=st.text_area("Core Coaching Theme");primary_framework=st.text_input("Primary Nick Framework")
        st.caption("For fields with multiple values, separate items with semicolons.")
        secondary=st.text_area("Secondary Nick Frameworks");incidental=st.text_area("Incidental Nick Concepts");simple_tags=st.text_area("Simple Tags");emotional=st.text_area("Emotional Themes");audience=st.text_area("Target Audience");stage=st.text_area("Weight Loss Stage");topic_tags=st.text_area("Topic Tags");queries=st.text_area("Search Queries");hidden=st.text_area("Hidden Concepts");myths=st.text_area("Myths Debunked");takeaways=st.text_area("Key Takeaways")
        submitted=st.form_submit_button("Save new episode",type="primary",use_container_width=True)
        if submitted:
            upload_text="";upload_name=""
            if uploaded is not None:
                upload_name=uploaded.name;upload_text=uploaded.getvalue().decode("utf-8-sig",errors="replace")
            final_transcript=upload_text or transcript.strip();final_filename=upload_name or filename.strip()
            if not title.strip(): st.error("Episode title is required.")
            elif not youtube_url.strip(): st.error("YouTube URL is required.")
            elif not final_filename: st.error("Transcript filename is required.")
            elif not final_transcript: st.error("Upload or paste the transcript.")
            else:
                try:
                    eid=save_manual_episode({"episode_number":int(number),"episode_title":title.strip(),"publish_date":publish_date,"episode_type":episode_type,"success_story":success_story,"youtube_url":youtube_url.strip(),"caller":caller.strip(),"transcript_filename":final_filename,"transcript":final_transcript,"main_category":main_category.strip(),"central_question":central_question.strip(),"central_struggle":central_struggle.strip(),"core_coaching_theme":core_theme.strip(),"primary_nick_framework":primary_framework.strip(),"secondary_nick_frameworks":secondary,"incidental_nick_concepts":incidental,"simple_tags":simple_tags,"emotional_themes":emotional,"target_audience":audience,"weight_loss_stage":stage,"topic_tags":topic_tags,"search_queries":queries,"hidden_concepts":hidden,"myths_debunked":myths,"key_takeaways":takeaways})
                    st.success(f"EP-{int(number):03d} was saved. It is now searchable and available in All Episodes.")
                except ValueError as error: st.error(str(error))

elif page == "Topics":
    topic_rows = c.execute("SELECT value name,COUNT(DISTINCT episode_id) n FROM (SELECT episode_id,main_category value FROM episode_enrichment WHERE main_category<>'' UNION ALL SELECT episode_id,value FROM enrichment_values WHERE kind='topic_tags') GROUP BY value ORDER BY n DESC,value").fetchall()
    chosen = st.selectbox("Browse a topic", [r["name"] for r in topic_rows]) if topic_rows else None
    if chosen:
        st.caption(f"{next(r['n'] for r in topic_rows if r['name']==chosen)} episodes")
        rows = c.execute("SELECT DISTINCT e.* FROM episodes e JOIN (SELECT episode_id,main_category value FROM episode_enrichment WHERE main_category<>'' UNION ALL SELECT episode_id,value FROM enrichment_values WHERE kind='topic_tags') x ON x.episode_id=e.id WHERE x.value=? ORDER BY e.episode_number,e.episode_title", (chosen,)).fetchall()
        for row in rows: result_card(row, "topic")

elif page == "Call-In Episodes":
    st.subheader("Call-In Episodes")
    st.caption("Live call-in shows and episodes built around caller questions.")
    placeholders = ",".join("?" for _ in CALL_IN_EPISODE_NUMBERS)
    rows = c.execute(
        f"SELECT * FROM episodes WHERE episode_number IN ({placeholders}) ORDER BY episode_number",
        CALL_IN_EPISODE_NUMBERS,
    ).fetchall()
    st.caption(f"{len(rows)} episodes")
    for row in rows:
        result_card(row, "call-in")

elif page == "Quotes":
    query = st.text_input("Search quotes", placeholder="Try motivation, identity, consistency…")
    sql = "SELECT q.*,e.episode_id,e.episode_title FROM quotes q JOIN episodes e ON e.id=q.episode_id"
    params = []
    if query: sql += " WHERE q.quote LIKE ? OR q.topic LIKE ? OR q.speaker LIKE ?"; params = [f"%{query}%"]*3
    rows = c.execute(sql+" ORDER BY e.episode_number,q.id", params).fetchall()
    if not rows: st.info("No reviewed quotes match yet. Quotes are never fabricated.")
    for row in rows:
        with st.container(border=True): st.write(f'“{row["quote"]}”'); st.caption(f'{row["episode_id"]} · {row["speaker"] or "Unknown speaker"} · {row["topic"] or "Uncategorized"}')

elif page == "Email Ideas":
    topics_list = ["All"]+[r[0] for r in c.execute("SELECT DISTINCT topic FROM email_ideas WHERE topic<>'' ORDER BY topic")]
    chosen = st.selectbox("Filter by topic", topics_list)
    rows = c.execute("SELECT i.*,e.episode_id,e.episode_title FROM email_ideas i JOIN episodes e ON e.id=i.episode_id WHERE ?='All' OR i.topic=? ORDER BY e.episode_number,i.id", (chosen,chosen)).fetchall()
    if not rows: st.info("No reviewed email ideas are available for this selection yet.")
    for row in rows:
        with st.container(border=True): st.subheader(row["suggested_subject"] or "Email idea"); st.write(row["idea"]); st.caption(f'{row["episode_id"]} · {row["topic"] or "Uncategorized"} · CTA: {row["cta"] or "—"}')

elif page == "Short Ideas":
    query = st.text_input("Search hooks", placeholder="Search a topic or hook…")
    sql = "SELECT h.*,e.episode_id,e.episode_title FROM short_hooks h JOIN episodes e ON e.id=h.episode_id"
    params=[]
    if query: sql += " WHERE h.hook LIKE ? OR h.topic LIKE ?"; params=[f"%{query}%"]*2
    rows=c.execute(sql+" ORDER BY e.episode_number,h.id",params).fetchall()
    if not rows: st.info("No reviewed short-form hooks match yet.")
    for row in rows:
        with st.container(border=True): st.subheader(row["hook"]); st.caption(f'{row["episode_id"]} · {row["topic"] or "Uncategorized"} · {row["exact_or_adapted"] or "Unspecified"}')

else:
    rows = c.execute("SELECT e.episode_id,e.episode_title,p.issue_type,p.detail FROM processing_issues p JOIN episodes e ON e.id=p.episode_id ORDER BY e.episode_number,p.id").fetchall()
    st.metric("Review items", len(rows))
    issue_filter = st.text_input("Filter the review queue", placeholder="Search an episode or issue…")
    for row in rows:
        text = f"{row['episode_id']} {row['episode_title']} {row['issue_type']} {row['detail']}"
        if not issue_filter or issue_filter.lower() in text.lower():
            with st.container(border=True): st.write(f"**{row['episode_id']} · {row['episode_title']}**"); st.caption(f"{row['issue_type']} · {row['detail']}")

episode_dialog()
