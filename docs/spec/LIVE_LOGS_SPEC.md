# LIVE_LOGS Spec — live logs for superusers (backend)

Update this doc first when changing live-log behaviour, then code + tests. How it is built:
[LIVE_LOGS_DESIGN](../design/LIVE_LOGS_DESIGN.md). Status 2026-10-06: built (branch `feat/live-logs`). The
UI page is out of scope here.

## Content

### REQ-LL-01 — One stream
Server (API) lines and engine lines in one stream, each marked `source: server | engine`. Engine covers
every engine process on this machine — command line, `--detach` and web runs — and every command
(generate, export, reexport, resume, …).
**Verification:** a web run and a CLI run at once both appear, beside the API's lines.

### REQ-LL-02 — Record fields
`seq`, `ts` (millisecond, server local time with offset), `level`, `source`, `logger`, `message`
(a traceback stays inside its record), `pid`, and where known: `project`, `version`, `job`, `run`
(generate / export / reexport / resume), `step` (`Parse`, `Derive`, `Views`, `Export SWE.3`,
`Export SWE.4`), `components` (Views and Export steps).
**Verification:** an engine record from each phase carries its step; an exception logs as one record.

### REQ-LL-03 — API calls
One server line per POST, PUT and DELETE and per error response (≥ 400): method, path, status, duration,
user id. A GET that succeeds is not logged. Every line written while a request is handled carries the
project, version and job named in its path.
**Verification:** `POST …/jobs` is logged with its project; `GET …/jobs/{id}` is not; a 500 is.

### REQ-LL-04 — Job and run kind on engine lines
Filled in when the API reads the line: the job that was running for that version at that time (one
writer per version makes it exact). A CLI run has none.
**Verification:** engine lines of a web run carry its `job` and `run`; a CLI run's carry neither.

---

## Reading

### REQ-LL-05 — Tail
`GET /api/v1/admin/logs?lines=N` returns the last N matching records, oldest first, and the cursor
(the last `seq`). N defaults to `logs.liveLines` (500); above `logs.maxLines` (2000) it is clamped.
**Verification:** no `lines` → 500 records; `lines=5000` → 2000.

### REQ-LL-06 — Filters
`level` (minimum; default `logs.level`, `INFO`), `source`, `project`, `version`, `job`, `step`. Records
are always written at DEBUG, so `level=DEBUG` shows them without a restart.
**Verification:** `level=WARNING` returns no INFO record; `job=…` returns that job's server and engine lines.

### REQ-LL-07 — Order
Records are merged by `ts`; each process's own records keep their order.
**Verification:** two processes' interleaved records come back in time order.

### REQ-LL-08 — Live
`GET /api/v1/admin/logs/stream` (SSE): one `log` event per record with `id: <seq>`, the same filters, a
heartbeat every 15 s. `after=<seq>` or `Last-Event-ID` resumes with no gap or repeat. When records
between `after` and the oldest kept are gone -- or `after` was numbered by an API process that has
since restarted -- the stream first sends a `gap` event: reload the tail.
**Verification:** a record written after the stream opens arrives within 2 s; a reconnect with the last
id misses nothing; `after` beyond the newest `seq` gets `gap`.

---

## Access and safety

### REQ-LL-09 — Superuser only
Every route: 401 without sign-in, 403 for a user who is not a superuser. Read-only.
**Verification:** a project admin who is not a superuser gets 403.

### REQ-LL-10 — Stream sign-in by ticket
`POST /api/v1/admin/logs/ticket` (signed in, superuser) returns a random ticket valid 60 s, usable
once. The stream takes `?ticket=…` (a browser `EventSource` cannot send a header). Unknown, used or
expired ticket → 401. A reconnect takes a new ticket and `after=<last seq>`.
**Verification:** the stream without a ticket, with a reused one, or 61 s later → 401.

### REQ-LL-11 — Secrets masked
Before a record leaves the server: passwords in connection URLs, `Authorization` / `Bearer` values,
`api_key` / `token` / `password` values, and the exact LLM key and database password configured.
**Verification:** a logged DSN `postgresql://u:secret@h/db` reads `postgresql://u:***@h/db`.

---

## Operation

### REQ-LL-12 — Cost
A tail never reads a whole file. Runs are not slowed or locked by the reader; a file being written by
another process is readable (Windows). Lines continue across midnight.
**Verification:** a tail over a 1 GB day of logs answers in under a second.

### REQ-LL-13 — Retention
Live log files older than `logs.keepDays` (30) days are deleted.
**Verification:** a day folder 31 days old is gone after the daily clean-up.

### REQ-LL-14 — Config
`logs` in `config.defaults.json`: `liveLines` 500, `maxLines` 2000, `level` "INFO", `keepDays` 30. Read
on each request.
**Verification:** changing `level` changes the next response without a restart.

### REQ-LL-15 — Nothing existing changes
`logs/run_<date>.log`, each run's `run.log` and the job stream `GET …/jobs/{id}/events` keep their
format. One addition: a step that configured no logging (`model_deriver.py`, `swe4_exporter.py`, …)
now configures it as `parser.py` always has, so its log records reach the console and
`run_<date>.log` too.
**Verification:** the job stream and `run.log` are unchanged; `run_<date>.log`'s line format is.

---

## Limitations
- A step's `print()` output is copied in (INFO, logger = the script); other programs' output -- the
  API's own prints, git, the diagram renderers -- is not.
- One machine and one API process (assumed); a run on another machine is not seen.

## Open items
- None — agreed 2026-10-06 (superuser only, every engine run, whole stream, 500 / 2000 lines, INFO with
  DEBUG configurable, SSE, tail only, masking, one machine, 30 days, ticket sign-in, job from the API).
