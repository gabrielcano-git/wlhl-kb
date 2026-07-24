# WLHL Knowledge Base

The WLHL Knowledge Base is a password-protected Streamlit application for searching podcast episodes, reviewing transcripts and coaching concepts, editing episode metadata, and assembling source-grounded marketing prompts.

## Runtime data model

A local SQLite database file is the only runtime data source. Every application read and write—including episodes, search indexes, Prompt Workspace settings, presets, and prompt history—uses that file. Reads are local-disk fast, with no network round-trips.

The database path is resolved from `WLHL_SQLITE_PATH` (environment, Streamlit secrets, or `.env`) and defaults to the bundled `database-init.sqlite` seed. In Docker it defaults to `/data/wlhl.sqlite` on a persistent volume, seeded from `database-init.sqlite` on first boot; existing data is never overwritten.

The app opens one connection per Streamlit user session in WAL mode (concurrent readers never block; competing writers wait up to `busy_timeout` for the lock), reuses it across that session's reruns, validates the required WLHL schema before initializing search, and closes it on logout. CRUD operations update source and derived search tables in one transaction and roll back together on failure.

## Local Docker

Docker Desktop is the supported local runtime. Copy the environment template and set the login credentials:

```bash
cp .env.example .env
```

```dotenv
# Optional: leave blank to use the /data/wlhl.sqlite volume default.
WLHL_SQLITE_PATH=
WLHL_AUTH_USERNAME=your-local-login
WLHL_AUTH_PASSWORD=use-a-strong-password
```

Start the application:

```bash
docker compose up --build
```

Open <http://localhost:8501>. Runtime data lives on the named `wlhl-data` volume mounted at `/data`, so it survives rebuilds and `docker compose down`. The project bind mount supports local code iteration.

Check container health with:

```bash
curl --fail http://localhost:8501/_stcore/health
```

The sidebar's **Stop App** control is shown only in this local Docker runtime.

## Deploying to a DigitalOcean droplet

The app is lightweight (Streamlit + stdlib `sqlite3`); a 1–2 GB droplet is plenty for an internal tool with a handful of users.

1. Create the droplet and install Docker + the Compose plugin.
2. `git clone` this repository onto the droplet.
3. Create `.env` with strong `WLHL_AUTH_USERNAME` / `WLHL_AUTH_PASSWORD`. Leave `WLHL_SQLITE_PATH` blank to use the `/data` volume default.
4. Start it: `docker compose up -d --build`. `restart: unless-stopped` brings it back after reboots.
5. Put a reverse proxy (Caddy or nginx) in front for TLS and a domain, forwarding to `:8501` **with WebSocket upgrade enabled** (Streamlit needs it).

The database lives on the `wlhl-data` Docker volume. Back it up with `docker run --rm -v wlhl-data:/data -v "$PWD":/backup alpine cp /data/wlhl.sqlite /backup/`, or snapshot the droplet.

> Streamlit Community Cloud is **not** suitable for this runtime: its filesystem is ephemeral, so local SQLite writes would be lost on restart. Use a droplet (or any host with a persistent disk).

Never commit `.env` or `.streamlit/secrets.toml`. If the database file is missing, credentials are rejected, or required tables are absent, startup stops with a safe message.

## Features

- **All Episodes** browses and exports the episode catalog.
- **Search** ranks matches across titles, categories, questions, summaries, frameworks, semantic metadata, related content, and transcripts. FTS5 improves ranking when available; portable document search remains available without it.
- **Topics** and **Call-In Episodes** provide focused browsing.
- **Add Episode** and episode editors update the database and all search indexes transactionally.
- **Prompt Workspace** selects episode material and builds a prompt for use in ChatGPT, Claude, Gemini, or another model. The app assembles the prompt but does not call an AI API.
- **Writing Settings**, presets, and the latest 50 prompts are persisted in the database.

## Development and tests

Deployment dependencies remain in `requirements.txt`; test dependencies are separate:

```bash
python -m pip install -r requirements-dev.txt
pytest
python -m compileall -q app.py authentication.py database_connection.py db_compat.py episode_service.py prompt_workspace.py prompt_workspace_ui.py unified_search.py scripts
docker compose config
```

Unit and integration tests write only to temporary SQLite copies.

## Legacy migration utility

`scripts/migrate_to_turso.py` is a standalone, one-way export from a local SQLite database to a Turso remote. It is not used by the app and is retained only for historical migrations. It requires an explicit source path, validates that `episodes` exists, refuses a zero-episode source, filters FTS shadow tables, and does not modify its source.

## Project layout

- `app.py` — Streamlit interface and session lifecycle
- `database_connection.py` — SQLite configuration, connection, safe errors, and schema validation
- `docker-entrypoint.sh` — seeds the runtime database on first boot, then starts Streamlit
- `episode_service.py` — transactional episode and related-content operations
- `unified_search.py` — portable cross-table index and optional FTS5 ranking
- `prompt_workspace.py` / `prompt_workspace_ui.py` — prompt persistence, assembly, and interface
- `scripts/migrate_to_turso.py` — legacy one-way export utility (not used at runtime)
- `tests/` — isolated tests against temporary SQLite copies
