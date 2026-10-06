# Live logs — design

How [LIVE_LOGS_SPEC](../spec/LIVE_LOGS_SPEC.md) is built. Status 2026-10-06: built (branch `feat/live-logs`).

```
engine processes ─┐  each writes its own file          API process
(CLI, detached,   ├─► logs/live/<date>/engine-<pid>.jsonl ─┐
 web runs)        ┘                                          ├─► reader thread ─► buffer ─► /admin/logs
API (server)  ─────► logs/live/<date>/server-<pid>.jsonl ───┘   (mask, job)     (20 000)    /admin/logs/stream
```

**Why files, one per process:** no two processes write one file (safe on Windows); logging works when
the database is down; no load on the database the runs use; SQLite and PostgreSQL alike. A database
copy for history search can be added later from the reader without changing this (decided 2026-10-06).

## 1. Writer — `engine/core/logging_setup.py`

- `configure_logging` (every engine process goes through it, `run.py` and the lazy `get_logger`)
  adds a `LiveLogHandler`. The API installs the same handler with `source="server"`.
- File: `<data root>/logs/live/<YYYY-MM-DD>/<source>-<pid>.jsonl`, data root from `core.paths` (a
  detached run already gets it). A new file when the local date changes. Level DEBUG always.
- One JSON object per line, written and flushed whole; a handler error is swallowed (a log line never
  breaks a run).
- A filter fills the context: `project`, `version` from `core.run_context`; `step` from the script
  name (`parser.py` → `Parse`, `model_deriver.py` → `Derive`, `run_views.py` → `Views`,
  `docx_exporter.py` → `Export SWE.3`, `swe4_exporter.py` → `Export SWE.4`); `components` from
  `--allowed-components`; in the API, the request's ids from a `contextvar`.
- Each step script (`parser.py`, `model_deriver.py`, `run_views.py`, `docx_exporter.py`,
  `swe4_exporter.py`, `flowchart_engine.py`) calls `start_phase_logging()` at start: logging
  configured as the first `get_logger` would (`model_deriver.py` and `swe4_exporter.py` logged
  nowhere in a run without the LLM), and what it prints copied to the live log as INFO
  (`_PrintsToLiveLog`; the console gets what it got before). Only in the step's own process --
  the API and the tests import these modules. A step that reads `--version-id` itself
  (`swe4_exporter.py`) gets `project`/`version` from its command line.
- The line format of `logs/run_<date>.log` and the console is untouched.

## 2. Server lines — `api/main.py`, `api/middleware/request_log.py`

- The API process imports the engine's modules, which configure logging -- so it has always written
  `logs/run_<date>.log` too, and now has the live handler. `api/main.py` marks it `server`
  (`set_live_source`) before importing its routes. At startup the same handler is added to uvicorn's
  own logger, which does not propagate when uvicorn configured it: start-up and error messages reach
  the live log, uvicorn's access lines do not.
- Middleware: sets the `contextvar` (project, version, job from the path) for the request; after it,
  logs one line for POST / PUT / DELETE and for any status ≥ 400 or exception:
  `POST /api/v1/projects/p1/jobs -> 202 (184 ms) user=u1`. Never the query string (some routes take a
  token there). The `api.request` logger writes to the live log only (it does not propagate), so the
  console and `run_<date>.log` are as before. Plain ASGI, not `BaseHTTPMiddleware`: SSE streams pass
  through untouched.

## 3. Reader — `api/services/live_logs.py`

- One thread, started with the API. Every second: list today's and yesterday's folders, read new bytes
  per file (offset per file; a partial last line waits for its end), parse, mask, enrich, sort the
  batch by `ts`, append to a `deque(maxlen=20000)` with `seq` +1 each.
- Startup: fill the buffer from the newest files backwards (each read from its end), so the tail shows
  runs that happened while the API was off.
- Enrich: a map version → running job (`db.jobs`, refreshed each pass) gives `job` and `run`
  (`job.mode`); one writer per version makes it exact.
- Mask: regexes for URL passwords, `Authorization`/`Bearer`, `api_key|token|password` values, plus the
  configured LLM key and database password replaced literally.
- Daily: delete day folders older than `logs.keepDays`.
- `seq` starts again at 1 when the API restarts: a stream whose `after` is beyond the newest `seq`
  gets a `gap` event first, as does one whose `after` the buffer has moved past.

## 4. Routes — `api/routes/admin_logs.py`

| Route | Answer |
|---|---|
| `GET /api/v1/admin/logs` | `{records: [...], cursor, lines, level}` — last N matching, oldest first |
| `POST /api/v1/admin/logs/ticket` | `{ticket, expiresIn: 60}` |
| `GET /api/v1/admin/logs/stream?ticket=&after=` | SSE `log` events (`id: seq`), heartbeat 15 s |

- `require_superuser` (new, `api/middleware/auth.py`) on the first two; the stream checks the ticket.
- Tickets: in memory, `{ticket: (user, expiry)}`, deleted on use. A reconnect takes a new ticket
  and `after=<last seq>` (`EventSource` cannot change its URL, so the page opens a new one).
- Filters (`level`, `source`, `project`, `version`, `job`, `step`) apply to tail and stream alike.

## 5. Config — `engine/config/config.defaults.json`

```json
"logs": {"liveLines": 500, "maxLines": 2000, "level": "INFO", "keepDays": 30}
```

## 6. Tests

`tests/unit/test_live_log_handler.py` (fields, step per script, traceback in one record, date switch,
the switch-off) · `tests/unit/test_live_logs_reader.py` (merge order, new files, partial lines,
masking, job enrichment, retention, backfill) · `tests/api/test_admin_logs.py` (401/403, 500 default /
2000 cap, filters, ticket once and 60 s, stream resume and `gap`, request lines: POST yes, GET no, 404
and 500 yes, ids reach a sync route) · `tests/e2e/test_live_log.py` (every step of a CLI run writes
under its version). The test suite's own process writes no live log (`LIVE_LOG_ENABLED`, set in
`tests/conftest.py`).
