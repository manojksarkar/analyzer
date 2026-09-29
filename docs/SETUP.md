# Install and run

From a fresh clone to the web app and the command line. Every command below was run on Windows 10
(Python 3.14, Node 24, PostgreSQL 16) on 2026-09-29. Commands run from the repo root unless a step
says otherwise.

## 1. What you need

| Tool | Version | What for |
|---|---|---|
| Python | 3.12 or newer | engine, API, tests |
| Node.js + npm | 20.19 / 22.12 or newer | web app; diagram rendering (Mermaid, Graphviz via WASM) |
| LLVM (libclang) | 17 | C++ parsing — default path `C:\Program Files\LLVM\bin\libclang.dll` |
| Google Chrome | any recent | draws the Mermaid diagrams (through puppeteer) |
| Git | any recent | the API clones project repositories |
| PostgreSQL | 16 | the database — or Docker, or SQLite for a local try-out (§4) |
| Ollama + `llama3.2` | optional | the LLM that writes descriptions; any gateway works instead (§3) |

Graphviz does not need installing: flowcharts are drawn by `@viz-js/viz` (npm).

## 2. Install

```
pip install -r requirements.txt
npm install
cd web-app
npm install
cd ..
```

`requirements.txt` is the complete Python set (engine, API, tests). The root `npm install` brings
the diagram tools (`@mermaid-js/mermaid-cli`, `puppeteer`, `@viz-js/viz`); the second one the web app.

## 3. Configure

Machine-specific settings and secrets go in `engine/config/config.local.json` (gitignored, merged
over `config.defaults.json`). Start from the template:

```
copy engine\config\config.local.json.example engine\config\config.local.json
```

- **`db`** — where PostgreSQL is (user, password, database). The `DATABASE_URL` environment variable
  wins over it when set.
- **`llm`** — the LLM endpoint. The default is a local Ollama (`http://localhost:11434`, model
  `llama3.2`): install Ollama, then `ollama pull llama3.2`. For a gateway, set `baseUrl` and its headers.
  To run without any LLM, add `"llm": {"descriptions": false, "behaviourNames": false}` — much faster,
  descriptions stay empty.
- **libclang** — if LLVM is not in `C:\Program Files\LLVM`, set `clang.llvmLibPath` and
  `clang.clangIncludePath` here.
- **Chrome** — `engine/config/puppeteer-config.json` names the Chrome executable; edit
  `executablePath` if yours is elsewhere.

## 4. Database

**Docker:** `docker compose up -d` starts PostgreSQL 16 with user, password and database `analyzer` —
the same values as the template's `db` section.

**Your own PostgreSQL:** create a login that may create databases (once, in `psql` as a superuser):

```sql
CREATE ROLE analyzer LOGIN PASSWORD 'analyzer' CREATEDB;
```

Then build the schema — it creates the database too. Re-run it after any `git pull` that brings a
migration:

```
python analyzer.py setup
```

`python analyzer.py setup --demo` also seeds demo projects and users (`alice@aspice.dev` / `secret`,
and `bob`, `carol`, `dave`, `eve` with the same password). Leave `--demo` off for a real installation.

**No PostgreSQL (local try-out):** `python tools/db_setup.py --sqlite engine/config/analyzer-dev.db`,
then put the line it prints (`{"db": {"url": "sqlite:///…"}}`) in `config.local.json`.

## 5. Check

```
python analyzer.py doctor
python analyzer.py check-llm
```

`doctor` checks Python packages, Node, the npm tools, Chrome and libclang, and names what is missing.
`check-llm` sends three prompts to the configured LLM. On this machine a local Ollama answered in
3–105 s per prompt — which is why a first run with the LLM on takes long (§6).

## 6. Run the web app

Two terminals, both started from the repo root.

**API** (port 8000):

```
python -m uvicorn api.main:app --port 8000
```

It prints which database it is using. On a database with no users it creates `admin@aspice.dev` /
`admin` — change that password after the first sign-in.

**Web app** (port 5173):

```
cd web-app
npm run dev
```

Open http://localhost:5173 and sign in. The app finds the API at `http://localhost:8000/api/v1`; for
another address, set `VITE_API_URL` in `web-app/.env` (see `web-app/.env.example`).

Then: **New Project** (the wizard) → **Run Analysis** on the Overview page → the documents appear under
**Documents** when the run completes. A run with the LLM on takes as long as the LLM needs — the
sample project took about 2 hours on a local Ollama the first time, minutes once its answers were cached.

## 7. Run from the command line

The same pipeline without the web app — `onboard` a project, then `generate` versions:
[CLI_COMMANDS.md](CLI_COMMANDS.md) walks through it end to end.

## 8. Tests

```
python -m pytest tests/unit tests/api --skip-pipeline
cd web-app
npm test
npm run test:api
```

`--skip-pipeline` skips the end-to-end suite that parses `SampleCppProject`. `npm run test:api` checks a
running API's responses against what the web app expects — write checks only run against
`localhost` ([web-app/TESTING.md](../web-app/TESTING.md)). It signs in as `alice@aspice.dev` /
`secret`, who exists only in a database set up with `--demo`; otherwise set `API_TEST_EMAIL` and
`API_TEST_PASSWORD`. The API tests run on in-memory databases;
only the app's start-up reaches the configured one (it adds `admin@aspice.dev` if missing).

## 9. When something is wrong

| Symptom | Look at |
|---|---|
| `setup` cannot reach or create the database | is PostgreSQL running; can the `db` user `CREATE DATABASE`; is `DATABASE_URL` set to something else |
| A run fails straight away | the red banner on the Overview page shows the error; `python analyzer.py doctor` |
| A run sits in Phase 2 for a long time | the LLM (§3, §5) — the progress bar shows how far it is |
| The web app says "Failed to fetch" | is the API running, and on the address the web app expects (§6) |
| Port 8000 or 5173 is in use | `--port <n>` for the API; `npm run dev -- --port <n>` for the web app, with `VITE_API_URL` to match |
