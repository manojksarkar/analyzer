# End-to-end commands — feat/incremental-into-webapi (onboard → document)

One server (`api/`); project + version metadata live in `api/db/data/*.json`; each version's
artifacts live in `workspaces/<projectId>/<commit[:16]>/` (checkout + model/ output/ manifest).
No `seed_workspace.py`, no `workspaces/<pid>/project.json`, no `versions/<id>/` tree.

```bash
BASE=http://localhost:8000/api/v1
```

### 0. Setup (once per machine)
```bash
pip install -r requirements.txt        # analyzer deps incl. libclang (Phase 1 parse)
pip install -r api/requirements.txt    # API server deps (FastAPI, jose, …)
npm install                            # mermaid-cli (mmdc) + Chromium for flowchart PNGs
```

### 1. Start the one server (JSON DB so the CLI sees the same data)
```bash
API_DB_BACKEND=json uvicorn api.main:app --reload --port 8000
# docs: http://localhost:8000/docs   (self-hosted Swagger; click Authorize, paste the token)
```

### 2. Sign in → bearer token (seed user; password `secret`)
```bash
TOKEN=$(curl -s -X POST "$BASE/auth/signin" -H "Content-Type: application/json" \
  -d '{"email":"alice@aspice.dev","password":"secret"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
AUTH=(-H "Authorization: Bearer $TOKEN")
```

### 3. Onboard the project (writes the DB record + workspaces/<pid>/config.json)
```bash
curl -s "${AUTH[@]}" -X POST "$BASE/projects" -H "Content-Type: application/json" -d '{
  "name":"SampleCpp","client":"demo","compliance_standard":"ASPICE",
  "repo_url":"https://github.com/vishal9359/SampleCppProject.git","default_branch":"main",
  "build_config":{}, "architecture_layers":[ /* layers/groups/components */ ]
}'
PID=<projectId from the response>      # e.g. p1a2b3c4
```

### 4. List commits
```bash
curl -s "${AUTH[@]}" "$BASE/projects/$PID/commits?branch=main"
```

### 5. Preview the baseline decision (read-only: full vs incremental)
```bash
curl -s "${AUTH[@]}" "$BASE/projects/$PID/baseline-preview?commit=<SHA>"
```

### 6. Generate — `POST /jobs` does what /generate did (full + incremental)
The Job spawns `generate.py` (mode `full`) or `engine.py` (mode `auto`, picks the nearest
ancestor as baseline). Same `StartJobRequest` schema the UI uses.
```bash
# First commit → full
curl -s "${AUTH[@]}" -X POST "$BASE/projects/$PID/jobs" -H "Content-Type: application/json" \
  -d '{"commit_sha":"<SHA1>","mode":"full","scope":{"type":"group","names":["Support"]}}'

# Later commit → auto-incremental (baseline auto-selected; explicit reference_version_id wins)
curl -s "${AUTH[@]}" -X POST "$BASE/projects/$PID/jobs" -H "Content-Type: application/json" \
  -d '{"commit_sha":"<SHA2>","mode":"auto","scope":{"type":"group","names":["Support"]},
       "no_llm":false,"narrowed_parse":false}'
# -> { "job_id": "...", "status": "queued" }
```
CLI equivalent (reads api/db/data + workspaces/<pid>/config.json; clones the commit on demand):
```bash
python src/incremental/generate.py --project-id $PID --branch main --commit <SHA1> --scope group:Support
python src/incremental/engine.py   --project-id $PID --branch main --commit <SHA2> --scope group:Support \
       [--base-version-id <baseCommit[:16]>] [--no-llm] [--narrowed-parse]
```

### 7. Job status / live log (SSE)
```bash
curl -s "${AUTH[@]}" "$BASE/projects/$PID/jobs/<jobId>"
curl -sN "${AUTH[@]}" "$BASE/projects/$PID/jobs/<jobId>/events"     # Server-Sent Events stream
curl -s "${AUTH[@]}" -X POST "$BASE/projects/$PID/jobs/<jobId>/cancel"
```

### 8. Versions (carry decision / baseline / regenerated / reused)
```bash
curl -s "${AUTH[@]}" "$BASE/projects/$PID/versions"
curl -s "${AUTH[@]}" "$BASE/projects/$PID/versions/<versionId>"
```

### 9. Documents (rendered from the version's commit dir)
```bash
curl -s "${AUTH[@]}" "$BASE/projects/$PID/documents?version_id=<versionId>"
curl -s "${AUTH[@]}" "$BASE/projects/$PID/documents/<docId>/render"
curl -sL "${AUTH[@]}" -o out.docx "$BASE/projects/$PID/documents/<docId>/download"
curl -sL "${AUTH[@]}" -o all.zip  "$BASE/projects/$PID/documents/export-all/download?version_id=<versionId>"
```

### 10. Compare two versions (by versionId, tag, or commit-sha prefix)
```bash
curl -s "${AUTH[@]}" "$BASE/projects/$PID/compare?current=<ref>&baseline=<ref>"
```

---

### Scope / flags (CLI ⇄ API)
```
scope        --scope project|layer:L|group:G|component:C1,C2   ⇄  {"type":"group","names":["Support"]}
full vs auto generate.py (full) | engine.py (auto)             ⇄  "mode":"full"|"auto"
baseline     --base-version-id <commit[:16]>                   ⇄  "reference_version_id":"<commit[:16]>"
no LLM       --no-llm                                          ⇄  "no_llm":true
data dict    --data-dict-id <id>                               ⇄  "data_dict_id":"<id>"
narrowed     --narrowed-parse (engine only, opt-in)            ⇄  "narrowed_parse":true
```

### Layout produced
```
workspaces/<pid>/config.json                 # per-project config (API writes it at onboarding)
workspaces/<pid>/<commit[:16]>/              # = the version: git checkout + model/ output/ documents/ manifest.json
workspaces/<pid>/cache/index.json            # cross-version reuse index
api/db/data/{projects,versions,documents,…}.json   # the DB the API + CLI both read
```

### samplecpp commits
```
C1=08d2f565cd03e72e82c32b57be965cf4a5a420dc   C3=3433fd6d6911151de2db93ba9ee24d99f792bc82
```
