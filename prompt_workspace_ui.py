"""Streamlit interface for the WLHL Prompt Workspace."""
from __future__ import annotations

import html
import json
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

from prompt_templates import CATEGORIES, TEMPLATES, TEMPLATES_BY_ID
from prompt_workspace import (
    SETTING_LABELS, add_history, assemble_prompt, clear_history, delete_history, delete_preset,
    duplicate_preset, get_last_mode, get_settings, init_schema, list_history, list_presets,
    load_episode_material, prompt_metrics, reset_setting_section, save_last_mode, save_preset,
    save_settings, validate_settings_import,
)

INCLUSION_OPTIONS = ["Database fields only", "Database fields plus relevant transcript excerpts", "Full transcript", "Custom selection"]
AUDIENCES = ["Existing WLHL audience", "New audience", "Weight loss beginners", "People currently trying to lose weight", "People struggling with weight regain", "People at a plateau", "Long-term weight loss maintainers", "Last Day One members", "Custom audience"]
TONES = ["Educational", "Personal", "Story-driven", "Encouraging", "Direct", "Reflective", "Practical", "Promotional", "Custom tone"]
CTAS = ["Listen to the full episode", "Watch on YouTube", "Join Last Day One", "Reply to the email", "Share the content", "Follow the show", "Read a related resource", "No CTA", "Custom CTA"]


def _init_state(conn):
    defaults = {
        "pw_step": 1, "pw_mode": get_last_mode(conn), "pw_template": "newsletter", "pw_topic": "",
        "pw_selected": [], "pw_inclusion": {}, "pw_custom_sources": {}, "pw_config": {},
        "pw_generated": "", "pw_original": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _set_step(step):
    st.session_state.pw_step = step


def _new_prompt():
    """Clear only the active workspace; keep settings, presets, and history."""
    prefixes = ("pw_", "pw-", "cfg-", "preset-")
    for key in list(st.session_state.keys()):
        if key.startswith(prefixes):
            st.session_state.pop(key, None)


def _select_episode(episode_id, selected):
    values = list(st.session_state.pw_selected)
    if selected and episode_id not in values:
        values.append(episode_id)
    if not selected and episode_id in values:
        values.remove(episode_id)
    st.session_state.pw_selected = values


def _move_selected(episode_id, direction):
    values = list(st.session_state.pw_selected)
    index = values.index(episode_id)
    target = index + direction
    if 0 <= target < len(values):
        values[index], values[target] = values[target], values[index]
    st.session_state.pw_selected = values


def _selected_panel(conn):
    st.markdown("### Selected episodes")
    selected = list(st.session_state.pw_selected)
    if not selected:
        st.info("Select one or more episodes from the results.")
        return
    st.button(
        f"Continue with {len(selected)} selected →",
        key="pw-selected-panel-continue",
        type="primary",
        use_container_width=True,
        on_click=_set_step,
        args=(3,),
    )
    for episode_id in selected:
        row = conn.execute("SELECT episode_id,episode_title FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not row:
            continue
        with st.container(border=True):
            st.markdown(f"**{row['episode_id']}**")
            st.write(row["episode_title"])
            current = st.session_state.pw_inclusion.get(str(episode_id), INCLUSION_OPTIONS[1])
            inclusion = st.selectbox("Source detail", INCLUSION_OPTIONS, index=INCLUSION_OPTIONS.index(current), key=f"pw-include-{episode_id}")
            st.session_state.pw_inclusion[str(episode_id)] = inclusion
            if inclusion == "Custom selection":
                st.session_state.pw_custom_sources[str(episode_id)] = st.text_area("Custom source material", st.session_state.pw_custom_sources.get(str(episode_id), ""), key=f"pw-custom-{episode_id}")
            up, down, remove = st.columns(3)
            up.button("↑", key=f"pw-up-{episode_id}", on_click=_move_selected, args=(episode_id, -1), disabled=selected.index(episode_id) == 0, use_container_width=True)
            down.button("↓", key=f"pw-down-{episode_id}", on_click=_move_selected, args=(episode_id, 1), disabled=selected.index(episode_id) == len(selected) - 1, use_container_width=True)
            remove.button("Remove", key=f"pw-remove-{episode_id}", on_click=_select_episode, args=(episode_id, False), use_container_width=True)


def _history_panel(conn):
    with st.expander("Prompt history"):
        history = list_history(conn)
        if not history:
            st.caption("No prompts have been generated yet.")
        if history and st.button("Clear history", key="pw-clear-history"):
            st.session_state.pw_confirm_clear = True
        if st.session_state.get("pw_confirm_clear"):
            st.warning("Delete all prompt history?")
            yes, no = st.columns(2)
            if yes.button("Yes, clear history", key="pw-clear-yes"):
                clear_history(conn)
                st.session_state.pw_confirm_clear = False
                st.rerun()
            if no.button("Cancel", key="pw-clear-no"):
                st.session_state.pw_confirm_clear = False
                st.rerun()
        for item in history:
            template = TEMPLATES_BY_ID.get(item["content_type"])
            ids = json.loads(item["selected_episode_ids"] or "[]")
            with st.container(border=True):
                st.markdown(f"**{template.name if template else item['content_type']}** · {item['created_at']}")
                st.caption(f"{item['topic'] or 'No topic'} · {len(ids)} episode(s) · {len(item['generated_prompt']):,} characters")
                reopen, duplicate, copy, delete = st.columns(4)
                if reopen.button("Reopen", key=f"hist-open-{item['id']}", use_container_width=True):
                    st.session_state.pw_generated = item["generated_prompt"]
                    st.session_state.pw_original = item["generated_prompt"]
                    st.session_state.pw_step = 4
                    st.session_state.pw_template = item["content_type"]
                    st.session_state.pw_topic = item["topic"] or ""
                    st.session_state.pw_selected = ids
                    st.rerun()
                if duplicate.button("Duplicate", key=f"hist-dup-{item['id']}", use_container_width=True):
                    st.session_state.pw_generated = item["generated_prompt"]
                    st.session_state.pw_original = item["generated_prompt"]
                    st.session_state.pw_step = 4
                    st.rerun()
                with copy:
                    _copy_button(item["generated_prompt"], "Copy")
                if delete.button("Delete", key=f"hist-del-{item['id']}", use_container_width=True):
                    delete_history(conn, item["id"])
                    st.rerun()


def _presets_panel(conn, config=None):
    with st.expander("Prompt presets"):
        presets = list_presets(conn)
        if not presets:
            st.caption("No presets saved yet.")
        else:
            chosen = st.selectbox("Saved presets", presets, format_func=lambda row: row["name"], key="pw-preset-choice")
            rename = st.text_input("Preset name", chosen["name"], key="pw-preset-rename")
            load, rename_button, duplicate, delete = st.columns(4)
            if load.button("Load", key="preset-load", use_container_width=True):
                st.session_state.pw_template = chosen["content_type"]
                st.session_state.pw_config = json.loads(chosen["configuration_json"])
                st.session_state.pw_selected = json.loads(chosen["selected_episode_ids"]) if chosen["include_episodes"] else []
                st.session_state.pw_step = 3
                st.rerun()
            if rename_button.button("Rename", key="preset-rename", use_container_width=True):
                save_preset(conn, rename.strip() or chosen["name"], chosen["content_type"], json.loads(chosen["configuration_json"]), json.loads(chosen["selected_episode_ids"]) if chosen["include_episodes"] else [], chosen["id"])
                st.rerun()
            if duplicate.button("Duplicate", key="preset-duplicate", use_container_width=True):
                duplicate_preset(conn, chosen["id"])
                st.rerun()
            if delete.button("Delete", key="preset-delete", use_container_width=True):
                delete_preset(conn, chosen["id"])
                st.rerun()
        if config is not None:
            st.divider()
            name = st.text_input("Save current configuration as", key="pw-new-preset-name")
            include = st.checkbox("Include selected episodes in this preset", key="pw-preset-include-episodes")
            if st.button("Save current preset", key="pw-save-preset", use_container_width=True, disabled=not name.strip()):
                save_preset(conn, name.strip(), st.session_state.pw_template, config, st.session_state.pw_selected if include else [])
                st.success("Preset saved.")


def _copy_button(prompt, label="Copy prompt"):
    safe = json.dumps(prompt)
    components.html(
        f"""<button id="copy" style="width:100%;padding:10px;border:1px solid #bbb;border-radius:8px;background:white;cursor:pointer;font:14px sans-serif">{html.escape(label)}</button>
<script>const text={safe};document.getElementById('copy').onclick=async()=>{{await navigator.clipboard.writeText(text);document.getElementById('copy').innerText='Copied!';}};</script>""",
        height=48,
    )


def _render_results(conn, search_callback, enrichment_callback, open_episode_callback):
    main, panel = st.columns([2.2, 1])
    with main:
        st.markdown("### 2. Review and select episodes")
        st.caption(f"Search topic: **{st.session_state.pw_topic}**")
        with st.expander("Search filters"):
            left, right = st.columns(2)
            number = left.text_input("Episode number", key="pw-filter-number")
            category = right.text_input("Category contains", key="pw-filter-category")
            left, right = st.columns(2)
            tag = left.text_input("Tag contains", key="pw-filter-tag")
            minimum = right.slider("Minimum relevance", 0, 100, 0, key="pw-filter-relevance")
            use_dates = st.checkbox("Filter by publish date", key="pw-filter-dates")
            start = end = None
            if use_dates:
                left, right = st.columns(2)
                start = left.date_input("From", date(2025, 1, 1), key="pw-filter-start")
                end = right.date_input("To", date.today(), key="pw-filter-end")
            left, right = st.columns(2)
            has_transcript = left.checkbox("Has transcript", key="pw-filter-transcript")
            has_quotes = right.checkbox("Has supporting quotes", key="pw-filter-quotes")
            sort = st.selectbox("Sort", ["Most relevant", "Newest", "Oldest", "Episode number"], key="pw-sort")
        base = search_callback(st.session_state.pw_topic, {"type": "", "topic": "", "stage": "", "success": False, "start": None, "end": None})
        top = max([row.get("match_score", 0) for row in base] or [1])
        results = []
        for source in base:
            row = dict(source)
            meta = enrichment_callback(row["id"])
            score = round(100 * row.get("match_score", 0) / top) if top else 0
            searchable = " ".join([meta.get("main_category", "")] + meta.get("topic_tags", []) + meta.get("simple_tags", []))
            if number.strip() and number.strip() not in str(row["episode_number"]):
                continue
            if category.strip().lower() not in (meta.get("main_category") or "").lower():
                continue
            if tag.strip().lower() not in searchable.lower():
                continue
            if score < minimum:
                continue
            if start and row["publish_date"] < str(start):
                continue
            if end and row["publish_date"] > str(end):
                continue
            if has_transcript and not row["transcript"]:
                continue
            if has_quotes and not conn.execute("SELECT 1 FROM quotes WHERE episode_id=?", (row["id"],)).fetchone():
                continue
            row["relevance_percent"] = score
            row["pw_meta"] = meta
            results.append(row)
        if sort == "Newest":
            results.sort(key=lambda row: (row["publish_date"], row["episode_number"]), reverse=True)
        elif sort == "Oldest":
            results.sort(key=lambda row: (row["publish_date"], row["episode_number"]))
        elif sort == "Episode number":
            results.sort(key=lambda row: (row["episode_number"], row["episode_title"]))
        st.caption(f"{len(results)} relevant episode(s)")
        for row in results[:30]:
            meta = row["pw_meta"]
            with st.container(border=True):
                checked = st.checkbox(f"{row['episode_id']} · {row['episode_title']}", value=row["id"] in st.session_state.pw_selected, key=f"pw-select-{row['id']}")
                _select_episode(row["id"], checked)
                if checked:
                    st.button(
                        "Continue with selected episodes →",
                        key=f"pw-continue-here-{row['id']}",
                        type="primary",
                        use_container_width=True,
                        on_click=_set_step,
                        args=(3,),
                    )
                st.caption(" · ".join(value for value in [row["publish_date"], meta.get("main_category"), f"Relevance {row['relevance_percent']}%"] if value))
                if meta.get("central_question"):
                    st.markdown(f"**Central question:** {meta['central_question']}")
                summary = (meta.get("key_takeaways") or [row["short_summary"] or row["detailed_summary"] or ""])[0]
                if summary:
                    st.write(str(summary)[:500])
                if row.get("match_explanation"):
                    st.caption(f"Match: {row['match_explanation']}")
                if row.get("snippet"):
                    st.markdown(row["snippet"], unsafe_allow_html=True)
                st.button("View full episode details", key=f"pw-view-{row['id']}", on_click=open_episode_callback, args=(row["id"],))
        back, forward = st.columns(2)
        back.button("← Change content type", on_click=_set_step, args=(1,), use_container_width=True)
        forward.button("Configure prompt →", type="primary", on_click=_set_step, args=(3,), use_container_width=True, disabled=not st.session_state.pw_selected)
    with panel:
        _selected_panel(conn)


def _render_configuration(conn):
    main, panel = st.columns([2.2, 1])
    with main:
        template = TEMPLATES_BY_ID[st.session_state.pw_template]
        st.markdown(f"### 3. Configure {template.name}")
        cfg = dict(st.session_state.pw_config)
        cfg["topic"] = st.session_state.pw_topic
        cfg["main_angle"] = st.text_input("Main angle", cfg.get("main_angle", ""), key="cfg-angle")
        if "newsletter_angle" in template.available_fields:
            cfg["newsletter_angle"] = st.selectbox("Newsletter angle", ["Explain Nick’s story", "Challenge a common misconception", "Teach one practical lesson", "Use a listener question", "Connect multiple episodes around one topic", "Promote a specific episode", "Custom angle"], key="cfg-newsletter-angle")
        cta_default = cfg.get("cta", "No CTA")
        cfg["cta"] = st.selectbox("CTA", CTAS, index=CTAS.index(cta_default) if cta_default in CTAS else 7, key="cfg-cta")
        if cfg["cta"] == "Custom CTA":
            cfg["cta"] = st.text_input("Custom CTA", key="cfg-custom-cta")
        lengths = ["Short: 300–500 words", "Standard: 500–800 words", "Long: 800–1,200 words", "Custom"] if template.id == "newsletter" else ["Short", "Standard", "Long", "Custom"]
        cfg["length"] = st.selectbox("Length", lengths, index=1, key="cfg-length")
        if cfg["length"] == "Custom":
            cfg["length"] = st.text_input("Custom length", key="cfg-custom-length")
        if "number_of_options" in template.available_fields:
            cfg["number_of_options"] = st.number_input("Number of options", 1, 100, 10, key="cfg-options")
        if "number_of_emails" in template.available_fields:
            cfg["number_of_emails"] = st.number_input("Number of emails", 2, 20, 5, key="cfg-emails")
            cfg["email_goals"] = st.text_area("Goal of each email", key="cfg-email-goals")
            cfg["sequence_cta"] = st.text_input("Sequence CTA", key="cfg-sequence-cta")
        if st.session_state.pw_mode == "Advanced Prompt":
            cfg["central_lesson"] = st.text_area("Central lesson", cfg.get("central_lesson", ""), key="cfg-lesson")
            cfg["target_audience"] = st.selectbox("Target audience", AUDIENCES, key="cfg-audience")
            if cfg["target_audience"] == "Custom audience":
                cfg["target_audience"] = st.text_input("Custom audience", key="cfg-custom-audience")
            cfg["goal"] = st.text_input("Goal of the content", cfg.get("goal", ""), key="cfg-goal")
            cfg["tone"] = st.selectbox("Tone", TONES, key="cfg-tone")
            if cfg["tone"] == "Custom tone":
                cfg["tone"] = st.text_input("Custom tone", key="cfg-custom-tone")
            cfg["language"] = st.text_input("Language", "English", key="cfg-language")
            cfg["include_episode_references"] = st.checkbox("Include episode references", True, key="cfg-references")
            cfg["include_supporting_quotes"] = st.checkbox("Include supporting quotes", True, key="cfg-quotes")
            cfg["include_source_notes"] = st.checkbox("Include source notes at the end", True, key="cfg-notes")
            cfg["additional_instructions"] = st.text_area("Additional instructions", cfg.get("additional_instructions", ""), key="cfg-additional")
        else:
            cfg.update({"target_audience": cfg.get("target_audience", "Existing WLHL audience"), "tone": cfg.get("tone", "Practical"), "language": cfg.get("language", "English"), "include_episode_references": True, "include_supporting_quotes": True, "include_source_notes": True})
        st.session_state.pw_config = cfg
        back, generate = st.columns(2)
        back.button("← Change episode selection", on_click=_set_step, args=(2,), use_container_width=True)
        if generate.button("Generate prompt →", type="primary", use_container_width=True):
            settings = get_settings(conn)
            materials = [
                load_episode_material(
                    conn, episode_id, st.session_state.pw_topic,
                    st.session_state.pw_inclusion.get(str(episode_id), INCLUSION_OPTIONS[1]),
                    st.session_state.pw_custom_sources.get(str(episode_id), ""),
                    cfg.get("include_supporting_quotes", True),
                )
                for episode_id in st.session_state.pw_selected
            ]
            prompt = assemble_prompt(settings, template.id, cfg, materials)
            st.session_state.pw_generated = prompt
            st.session_state.pw_original = prompt
            add_history(conn, template.id, st.session_state.pw_topic, st.session_state.pw_selected, prompt, cfg)
            _set_step(4)
            st.rerun()
    with panel:
        _selected_panel(conn)


def _render_preview():
    heading, new_action = st.columns([3, 1])
    heading.markdown("### 4. Review and copy the final prompt")
    new_action.button(
        "＋ New Prompt",
        type="primary",
        use_container_width=True,
        on_click=_new_prompt,
    )
    prompt = st.text_area("Editable final prompt", st.session_state.pw_generated, height=620, key="pw-final-editor")
    st.session_state.pw_generated = prompt
    edited = prompt != st.session_state.pw_original
    metrics = prompt_metrics(prompt)
    one, two, three, four = st.columns(4)
    one.metric("Words", f"{metrics['words']:,}")
    two.metric("Characters", f"{metrics['characters']:,}")
    three.metric("Estimated tokens", f"{metrics['tokens']:,}")
    four.metric("Size", metrics["size"])
    if metrics["size"] == "Very large":
        st.warning("This prompt contains a large amount of source material. Consider using relevant excerpts instead of full transcripts.")
    view = st.radio("Preview", ["Plain text", "Formatted preview"], horizontal=True, key="pw-preview-mode")
    if view == "Formatted preview":
        st.markdown(f"<pre style='white-space:pre-wrap'>{html.escape(prompt)}</pre>", unsafe_allow_html=True)
    copy_col, download_col = st.columns(2)
    with copy_col:
        _copy_button(prompt)
    with download_col:
        st.download_button("Download as .txt", prompt, file_name=f"WLHL_{st.session_state.pw_template}_prompt.txt", mime="text/plain", use_container_width=True)
    if edited:
        st.caption("You have manually edited this prompt. Your changes will not be overwritten unless you reset or deliberately regenerate it.")
    selection, configuration, reset = st.columns(3)
    selection.button("← Episode selection", on_click=_set_step, args=(2,), use_container_width=True)
    configuration.button("← Configuration", on_click=_set_step, args=(3,), use_container_width=True)
    if reset.button("Reset changes", use_container_width=True, disabled=not edited):
        st.session_state.pw_generated = st.session_state.pw_original
        st.rerun()
    if st.button("Regenerate prompt", use_container_width=True):
        if edited:
            st.session_state.pw_confirm_regenerate = True
        else:
            _set_step(3)
            st.rerun()
    if st.session_state.get("pw_confirm_regenerate"):
        st.warning("Regenerating will replace your manual edits. Continue?")
        yes, no = st.columns(2)
        if yes.button("Yes, regenerate", key="regen-yes"):
            st.session_state.pw_confirm_regenerate = False
            _set_step(3)
            st.rerun()
        if no.button("Cancel", key="regen-no"):
            st.session_state.pw_confirm_regenerate = False
            st.rerun()


def render_prompt_workspace(conn, search_callback, enrichment_callback, open_episode_callback):
    init_schema(conn)
    _init_state(conn)
    st.subheader("Prompt Workspace")
    st.caption("Research Turso episodes and build a complete prompt in this app. Nothing is sent to an AI service.")
    mode = st.radio("Workspace mode", ["Quick Prompt", "Advanced Prompt"], horizontal=True, index=0 if st.session_state.pw_mode == "Quick Prompt" else 1, key="pw-mode-widget")
    if mode != st.session_state.pw_mode:
        st.session_state.pw_mode = mode
        save_last_mode(conn, mode)
    st.progress(st.session_state.pw_step / 4, text=f"Step {st.session_state.pw_step} of 4")
    _presets_panel(conn, st.session_state.pw_config if st.session_state.pw_step >= 3 else None)
    _history_panel(conn)
    if st.session_state.pw_step == 1:
        st.markdown("### 1. What do you want to create?")
        category = st.selectbox("Category", CATEGORIES, key="pw-category")
        available = [template for template in TEMPLATES if template.category == category]
        current = next((template for template in available if template.id == st.session_state.pw_template), available[0])
        template = st.selectbox("Content type", available, index=available.index(current), format_func=lambda item: item.name, key="pw-template-widget")
        st.session_state.pw_template = template.id
        st.caption(template.description)
        topic = st.text_input("Topic, theme, question, or keyword", st.session_state.pw_topic, placeholder="Example: healthy relationship with food", key="pw-topic-widget")
        st.session_state.pw_topic = topic
        if st.button("Search episodes →", type="primary", use_container_width=True, disabled=not topic.strip()):
            _set_step(2)
            st.rerun()
    elif st.session_state.pw_step == 2:
        _render_results(conn, search_callback, enrichment_callback, open_episode_callback)
    elif st.session_state.pw_step == 3:
        _render_configuration(conn)
    else:
        _render_preview()


def render_writing_settings(conn):
    init_schema(conn)
    settings = get_settings(conn)
    st.subheader("Writing Settings")
    st.caption("These reusable instructions are saved in the Turso WLHL database and are included automatically in generated prompts.")
    with st.form("writing-settings"):
        updated = dict(settings)
        for key, label in SETTING_LABELS.items():
            height = 520 if key == "nicks_writing_style" else 220 if key in {"master_prompt", "nick_voice", "content_rules"} else 150
            updated[key] = st.text_area(label, settings.get(key, ""), height=height, key=f"setting-{key}")
        st.markdown("### Content-specific instructions")
        content = dict(settings.get("content_type_instructions", {}))
        editable_ids = {"newsletter", "promotional_email", "email_sequence", "blog_article", "instagram_caption", "instagram_carousel", "facebook_post", "youtube_community_post", "youtube_description", "podcast_show_notes", "youtube_titles", "thumbnail_text", "short_hooks", "landing_page", "sales_page_section", "lead_magnet", "episode_summary", "repurposing_plan"}
        for template in TEMPLATES:
            if template.id in editable_ids:
                content[template.id] = st.text_area(template.name, content.get(template.id, template.default_instructions), height=120, key=f"setting-template-{template.id}")
        updated["content_type_instructions"] = content
        if st.form_submit_button("Save settings", type="primary", use_container_width=True):
            save_settings(conn, updated)
            st.success("Writing settings saved to Turso.")
    st.divider()
    st.markdown("### Reset or transfer settings")
    reset_options = {label: key for key, label in SETTING_LABELS.items()}
    reset_options.update({f"Content type: {TEMPLATES_BY_ID[key].name}": f"content_type:{key}" for key in settings["content_type_instructions"] if key in TEMPLATES_BY_ID})
    selected = st.selectbox("Section to reset", list(reset_options), key="settings-reset-section")
    confirm = st.checkbox("I understand this will replace the current section with its default text.", key="settings-reset-confirm")
    if st.button("Reset section to default", disabled=not confirm, use_container_width=True):
        save_settings(conn, reset_setting_section(settings, reset_options[selected]))
        st.success("Section reset.")
        st.rerun()
    st.download_button("Export settings as JSON", json.dumps(settings, ensure_ascii=False, indent=2), file_name="WLHL_Writing_Settings.json", mime="application/json", use_container_width=True)
    uploaded = st.file_uploader("Import settings from JSON", type=["json"], key="settings-import")
    if uploaded and st.button("Import settings", use_container_width=True):
        try:
            save_settings(conn, validate_settings_import(json.loads(uploaded.getvalue().decode("utf-8-sig"))))
            st.success("Settings imported.")
            st.rerun()
        except (ValueError, json.JSONDecodeError) as error:
            st.error(str(error))
