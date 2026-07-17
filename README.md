# WLHL Knowledge Base

A portable, offline-first local search engine for The Weight Loss Hotline. The Streamlit application is the product. SQLite Full Text Search powers it; Excel, CSV, and JSON are backup/export formats.

The home screen lists every episode. Search, Topics, Call-In Episodes, and Prompt Workspace provide focused research paths.

The **All Episodes** page lists every episode by number and title. Its natural-language search separates results into:

- **Main topic is …** — the concept is central in the title, main category, central question, struggle, or core coaching theme.
- **… is mentioned** — the concept appears in frameworks, tags, discovery metadata, or the transcript but is not classified as the main focus.

For example, search `videos where I talked about the Common Sense Diet` to see episodes centered on the framework before episodes that only mention it.

## Prompt Workspace

**Prompt Workspace** turns episode research into a complete prompt that you can copy into ChatGPT, Claude, Gemini, or another LLM. The app does not generate marketing copy, call an AI API, require an API key, or send transcript data anywhere.

The **Instagram carousel** template creates a source-grounded prompt for exactly 10 connected slides, including concise on-slide copy, an image or design idea for every slide, a complete caption, CTA, relevant hashtags, and episode source reporting.

The local workflow is:

1. Choose Quick Prompt or Advanced Prompt and a content type.
2. Search a topic using the existing keyword and semantic episode index.
3. Review ranked results and explicitly select one or more episodes.
4. Choose database fields, relevant transcript excerpts, a full transcript, or custom source material for each episode.
5. Configure the angle, audience, tone, length, CTA, and content-specific options.
6. Review the editable final prompt, then copy it or download it as a text file.

The default source level uses database fields plus relevant transcript excerpts, which keeps prompts useful without automatically inserting every full transcript. The size indicator warns about unusually large prompts but never blocks the user.

**Writing Settings** stores the editable WLHL master prompt, source priority, Nick’s voice, detailed Nick’s Writing Style rules and voice check, philosophy, content rules, preferred and forbidden language, CTA rules, formatting rules, and content-type instructions. Settings can be reset section-by-section or imported/exported as JSON. The detailed writing-style section is automatically inserted into every generated prompt and requires the receiving AI to apply the voice rather than merely describe it.

Prompt presets and the latest 50 generated prompts are saved locally. Presets can optionally include episode selections; by default they save only the reusable configuration.

### Add a new prompt template

Open `prompt_templates.py` and add one `PromptTemplate` entry to `TEMPLATES`. Give it a unique `id`, category, description, default instructions, relevant field names, and output requirements. The workspace category and content-type menus update automatically. Add its `id` to `editable_ids` in `render_writing_settings()` only if it should have a dedicated editor on the Writing Settings page.

Default reusable writing instructions live in `DEFAULT_SETTINGS` inside `prompt_workspace.py`. On first use, the app copies them into the local `prompt_settings` table. Future edits are stored in SQLite and do not modify the code defaults.

## Manual content editing

Open any episode and expand **Edit Content — Quotes, Email Ideas & Short Hooks**. From there you can add, edit, or delete:

- memorable quotes, including speaker and topic;
- email ideas, including subject line and CTA;
- short hooks, marked as an exact quote or an adaptation.

Changes are saved immediately in `database.sqlite`. Quotes are also refreshed in the episode search index.

## Add an episode manually

Open **Add Episode** in the sidebar. Enter the episode number, title, date, YouTube URL, exact transcript filename, and either upload or paste the transcript. All analysis fields are optional and manual; separate multiple values with semicolons.

The app does not call an AI service. It saves the episode, analysis, and full-text search entries locally. Existing episode numbers and transcript filenames are rejected to protect current records. Uploaded transcript content is stored in SQLite and the original file is not moved, renamed, or overwritten.

## Project layout

- `app.py` — primary application and episode interfaces
- `prompt_templates.py` — modular content-type definitions
- `prompt_workspace.py` — local persistence, source extraction, and central prompt builder
- `prompt_workspace_ui.py` — Prompt Workspace and Writing Settings interface
- `database.sqlite` — normalized database and full-text index
- `database/` — Excel, CSV, and JSON exports
- `scripts/` — build, incremental update, search, and Excel export tools
- `config.json` — relative transcript-folder setting
- `processing_log.txt` — latest run summary
- `transcripts/` — optional portable inbox for newly published canonical transcript files
- `../YT Transcripts/` — original canonical read-only source used for this build (never copied or changed)

All saved transcript paths are relative. The application itself is self-contained because searchable transcript text is stored in SQLite. The original `.txt` source files were not duplicated.

## Install and launch

Install Python 3.10 or newer, open a terminal in this folder, then run:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The app opens locally in a browser. It needs no account, server, cloud service, or internet connection after Streamlit is installed.

### Streamlit login

Add the following private values in the app's **Settings → Secrets** field on
Streamlit Community Cloud (or locally in `.streamlit/secrets.toml`):

```toml
[auth]
username = "your-login"
password = "use-a-strong-password"
```

The application does not start the database connection until a visitor has
entered these credentials. Do not commit the actual credentials to the
repository.

### Turso migration

The local SQLite file remains the working copy. To migrate its current schema and contents to the configured Turso database, keep `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` in the untracked `.env` file, then run:

```bash
python3 scripts/migrate_to_turso.py
```

To inspect the migration without contacting Turso, use `python3 scripts/migrate_to_turso.py --dry-run`. The migration does not change `database.sqlite`.

## Search

Use the large search box for a word, phrase, problem, title, topic, framework, takeaway, transcript passage, or indexed search term. The app builds one local search document per episode from the episode table and every related analysis table. SQLite FTS5 supplies fast normalized matching, while field-aware ranking puts titles, concepts, semantic tags, lessons, summaries, and central questions above incidental transcript mentions. Each result explains the strongest reason it matched. Repeated matches across tables still return only one episode card.

The derived tables `unified_search_documents` and `unified_episode_search` are safe to rebuild. They do not replace or modify the original episode, transcript, enrichment, topic, quote, email-idea, or short-hook records.

Command-line search is also available:

```bash
python scripts/search_wlhl_knowledge_base.py "emotional eating"
python scripts/search_wlhl_knowledge_base.py "temporary goals" --limit 10
```

## Add or update episodes

1. Add the new `.txt` file to the project’s `transcripts` folder, or to the configured sibling transcript folder, using the canonical `EP-###` filename.
2. Do not rename older files after indexing unless the filename itself is intentionally being corrected.
3. Run `python update_database.py` or `python scripts/update_wlhl_knowledge_base.py`.
4. Restart or refresh Streamlit.

The update compares SHA-256 file hashes and processes only new or changed transcripts. Existing records remain in place and the search index is refreshed only for changed records. Processing commits after every episode, so an interrupted run resumes safely.

To perform a clean full build, run `python scripts/build_wlhl_knowledge_base.py`.

## Edit or delete an episode

Open any episode and expand **Edit Episode**. You can update its title, date, YouTube URL, episode type, caller, analysis, frameworks, tags, search queries, audience, takeaways, advice, resolution, and CTA. Saving immediately refreshes the local search indexes.

The canonical episode number, transcript filename, relative transcript path, and full transcript are protected from this editor. Use **Delete Episode** only when you intend to remove the record from this copy of the app. A confirmation is required. Deleting removes related database records and search-index entries, but it never deletes or modifies an original transcript file on disk.

## Import updated episode analysis

Place the latest reviewed CSV at:

```text
imports/WLHL_episode_enrichment.csv
```

Then run:

```bash
.venv/bin/python scripts/import_enrichment.py
```

The importer matches primarily by normalized episode number (`EP-090`, `EP 090`, `090`, and `90` are equivalent), validates the title, ignores identical duplicate rows, and refuses ambiguous matches. It updates the normalized `episode_enrichment`, `enrichment_values`, and `enrichment_search` tables inside `database.sqlite`. It never updates transcript text or YouTube URLs. A timestamped database backup is created under `database/backups/` before each import, and the validation result is saved to `database/enrichment_import_report.json`.

After importing, stop and reopen the app using `Abrir WLHL.command`, or refresh the browser if the app was already restarted.

## SQLite

Open `database.sqlite` with DB Browser for SQLite or the `sqlite3` command. Core source tables are `episodes`, `episode_enrichment`, `enrichment_values`, `topics`, `episode_topics`, `episode_terms`, `quotes`, `email_ideas`, `short_hooks`, and `processing_issues`. `unified_search_documents` combines their searchable content by episode and `unified_episode_search` is its FTS5 index. The older `episode_search` and `enrichment_search` indexes remain intact for compatibility. Prompt Workspace uses the separate `prompt_settings`, `prompt_presets`, and `prompt_history` tables; it never writes to the episode or transcript tables.

Example:

```sql
SELECT e.episode_id, e.episode_title
FROM unified_episode_search s JOIN episodes e ON e.id=s.rowid
WHERE unified_episode_search MATCH 'plateau';
```

## Excel and exports

`database/WLHL_Episode_Database.xlsx` is a formatted backup/export with the complete episode table, indexes, review queue, and dashboard. JSON keeps list fields as arrays. CSV serializes list fields as JSON arrays so commas inside values are preserved.

## Move to another computer

Zip `WLHL Knowledge Base` and send it normally. The application, indexed transcript text, database, and exports are already inside it. The original source files are not required for searching.

If Nick also needs the complete original source-file collection for maintenance, transfer the parent folder containing both sibling folders:

```text
youtube-transcripts/
├── YT Transcripts/
└── WLHL Knowledge Base/
```

Unzip without changing that relationship, install the one requirement, and launch Streamlit. Windows, macOS, and Linux all resolve the same relative paths.

## Semantic-enrichment status

Exact metadata and every transcript are fully indexed locally. Reviewed spreadsheet enrichment is available for the imported episode range and receives stronger search weight than incidental transcript mentions. Episodes without reviewed enrichment retain their existing metadata and full-text transcript search.

For highest-quality enrichment, use a reviewed batch produced by a trusted AI workflow. The safest options are a local model with adequate context and structured-output support, or an approved API after explicit consent regarding cost and data transfer. Import reviewed enrichment into the normalized tables, then rebuild exports and FTS.
