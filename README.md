# WLHL Knowledge Base

The WLHL Knowledge Base is a password-protected Streamlit application for searching podcast episodes, reviewing transcripts and coaching concepts, editing episode metadata, and assembling source-grounded marketing prompts.

## Runtime data model

Turso is the only runtime data source. Every application read and write—including episodes, search indexes, Prompt Workspace settings, presets, and prompt history—uses the configured remote database.

`database.sqlite`, `database-init.sqlite`, and other SQLite snapshots are not opened by the application. They may be retained as development fixtures, exports, or explicit migration sources. The configured Turso database already contains the production episodes; do not run the migration utility against it merely to start the app.

The app creates one Turso DB-API connection per Streamlit user session, reuses it across that session's reruns, validates the required WLHL schema before initializing search, and closes it on logout. CRUD operations update source and derived search tables in one transaction and roll back together on failure.

## Local Docker

Docker Desktop is the supported local runtime. Copy the environment template and set all four required values:

```bash
cp .env.example .env
```

```dotenv
TURSO_DATABASE_URL=libsql://your-database-your-org.turso.io
TURSO_AUTH_TOKEN=your-token
WLHL_AUTH_USERNAME=your-local-login
WLHL_AUTH_PASSWORD=use-a-strong-password
```

Start the application:

```bash
docker compose up --build
```

Open <http://localhost:8501>. Compose runs the Python 3.12 image as `linux/amd64`, which lets ARM64 Docker Desktop use the official `libsql==0.1.11` wheel through emulation. The project bind mount supports local code iteration, but the app never uses a mounted SQLite file for runtime data.

Check container health with:

```bash
curl --fail http://localhost:8501/_stcore/health
```

The sidebar's **Stop App** control is shown only in this local Docker runtime. `docker compose down` removes the stopped container.

## Streamlit Community Cloud

Deploy `app.py` with `requirements.txt`, then add these values to **Settings → Secrets**:

```toml
TURSO_DATABASE_URL = "libsql://your-database-your-org.turso.io"
TURSO_AUTH_TOKEN = "your-token"

[auth]
username = "your-login"
password = "use-a-strong-password"
```

Database secrets are top-level keys; login credentials belong under `[auth]`. Environment variables take precedence when both forms exist. Never commit `.env` or `.streamlit/secrets.toml`.

If configuration is absent, credentials are rejected, Turso is unreachable, or required tables are missing, startup stops with a safe message that does not reveal the database URL or token.

## Features

- **All Episodes** browses and exports the remote episode catalog.
- **Search** ranks matches across titles, categories, questions, summaries, frameworks, semantic metadata, related content, and transcripts. FTS5 improves ranking when available; portable document search remains available without it.
- **Topics** and **Call-In Episodes** provide focused browsing.
- **Add Episode** and episode editors update Turso and all search indexes transactionally.
- **Prompt Workspace** selects episode material and builds a prompt for use in ChatGPT, Claude, Gemini, or another model. The app assembles the prompt but does not call an AI API.
- **Writing Settings**, presets, and the latest 50 prompts are persisted in Turso.

## Development and tests

Deployment dependencies remain in `requirements.txt`; test dependencies are separate:

```bash
python -m pip install -r requirements-dev.txt
pytest
python -m compileall -q app.py authentication.py database_connection.py db_compat.py episode_service.py prompt_workspace.py prompt_workspace_ui.py unified_search.py scripts
docker compose config
```

Unit and integration tests write only to temporary SQLite copies. The real Turso check is opt-in and read-only:

```bash
RUN_TURSO_TEST=1 pytest -m turso tests/test_turso_readonly.py
```

It validates the schema, confirms `episodes = 127`, and reads one episode. It performs no insert, update, delete, DDL, or index rebuild.

## Explicit migration utility

Migration is a separate administrative operation, not part of startup. It requires an explicit source path, validates that `episodes` exists, refuses a zero-episode source, and filters FTS shadow tables.

Always inspect locally first; dry-run does not require Turso credentials:

```bash
python scripts/migrate_to_turso.py --source /absolute/path/to/source.sqlite --dry-run
```

Only for an intentionally empty destination, set `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`, confirm the target independently, then omit `--dry-run`:

```bash
python scripts/migrate_to_turso.py --source /absolute/path/to/source.sqlite
```

The migration does not modify its source. Do not run it against the already populated production Turso database.

## Project layout

- `app.py` — Streamlit interface and session lifecycle
- `database_connection.py` — Turso configuration, connection, safe errors, and schema validation
- `episode_service.py` — transactional episode and related-content operations
- `unified_search.py` — portable cross-table index and optional FTS5 ranking
- `prompt_workspace.py` / `prompt_workspace_ui.py` — prompt persistence, assembly, and interface
- `scripts/migrate_to_turso.py` — explicit one-way migration utility
- `tests/` — isolated tests plus an opt-in read-only Turso check
