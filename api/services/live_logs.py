"""The live log: reads the files every process writes and keeps the newest records in memory
(docs/spec/LIVE_LOGS_SPEC.md, docs/design/LIVE_LOGS_DESIGN.md §3).

One thread, started with the API. Every second it reads what was added to today's and
yesterday's files under `<data root>/logs/live/`, masks secrets, gives an engine record its job,
sorts the batch by time and appends it to a bounded buffer, numbering each record (`seq`) so a
stream can continue where it stopped. At start it fills the buffer from the end of the files, so
runs made while the API was off are in the tail too. Live folders older than `logs.keepDays`
are deleted once a day.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import deque
from typing import Callable, Dict, Iterable, List, Optional, Tuple

_log = logging.getLogger(__name__)

#: Records kept in memory: room for a filtered tail of `logs.maxLines`.
BUFFER = 20000
POLL_SECONDS = 1.0
#: At most this much of one file per pass -- a burst is read over several passes.
MAX_READ = 8 * 1024 * 1024
#: Start-up fill: the newest files, each read from its last bytes only.
BACKFILL_FILES = 200
BACKFILL_BYTES = 2 * 1024 * 1024

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
FILTER_KEYS = ("source", "project", "version", "job", "step")


# ---------------------------------------------------------------------------
# Masking (REQ-LL-11)
# ---------------------------------------------------------------------------
_PATTERNS = (
    # scheme://user:PASSWORD@host
    (re.compile(r"(\b[a-zA-Z][\w+.-]*://[^\s:/@]*:)([^\s@/]+)(@)"), r"\1***\3"),
    # Authorization: <anything up to the line's end or a quote>
    (re.compile(r"(?i)(\bauthorization\b[\"']?\s*[:=]\s*)[^\r\n\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(\bbearer\s+)[\w.~+/=-]+"), r"\1***"),
    # api_key=..., "token": "...", password: ...
    (re.compile(r"(?i)(\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|token|secret|"
                r"password|passwd|pwd)\b[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&}]+"), r"\1***"),
)


class Masker:
    def __init__(self, secrets: Iterable[str] = ()):
        # Longest first, so a secret that contains another is replaced whole.
        self.secrets = sorted({s for s in secrets if isinstance(s, str) and len(s) >= 4},
                              key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        return text


def configured_secrets() -> List[str]:
    """The secrets this machine's config holds: the database password, the LLM key and the
    values of the LLM's custom headers (`config.local.json` puts credentials there)."""
    out: List[str] = []
    try:
        from core.db import database_url
        from sqlalchemy.engine import make_url
        pw = make_url(database_url()).password
        if pw:
            out.append(str(pw))
    except Exception:                                   # noqa: BLE001
        pass
    try:
        from core.config import app_config
        llm = app_config().get("llm") or {}
        for key in ("apiKey", "api_key", "key", "token"):
            if isinstance(llm.get(key), str):
                out.append(llm[key])
        out.extend(v for v in (llm.get("customHeaders") or {}).values()
                   if isinstance(v, str) and len(v) >= 6)
    except Exception:                                   # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------
def _parse_ts(value) -> Optional[dt.datetime]:
    try:
        when = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _aware(value) -> Optional[dt.datetime]:
    if not isinstance(value, dt.datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def run_kind(mode: Optional[str]) -> str:
    """What a job did, from its `mode`."""
    return mode if mode in ("reexport", "export", "resume") else "generate"


class LiveLogReader:
    def __init__(self, root: str, *, jobs_for_version: Optional[Callable] = None,
                 secrets: Iterable[str] = (), buffer: int = BUFFER):
        self.root = root
        self._jobs_for_version = jobs_for_version
        self._mask = Masker(secrets)
        self._records: deque = deque(maxlen=buffer)
        self._seq = 0
        self._offsets: Dict[str, int] = {}
        self._partial: Dict[str, bytes] = {}
        self._lock = threading.Lock()
        self._jobs: Dict[str, Tuple[float, list]] = {}
        self._cleaned_on: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    # ---- files ------------------------------------------------------------
    def _files(self) -> List[str]:
        """Today's and yesterday's live files, oldest first by modification time."""
        today = dt.date.today()
        found = []
        for day in (today - dt.timedelta(days=1), today):
            folder = os.path.join(self.root, day.isoformat())
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                if name.endswith(".jsonl"):
                    path = os.path.join(folder, name)
                    try:
                        found.append((os.path.getmtime(path), path))
                    except OSError:
                        pass
        return [p for _, p in sorted(found)]

    def _parse(self, lines: Iterable[bytes]) -> List[dict]:
        out = []
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("ts") and rec.get("message") is not None:
                out.append(rec)
        return out

    def _read_new(self, path: str) -> List[dict]:
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        start = self._offsets.get(path, 0)
        if size < start:                                # replaced: read it again from the top
            start, self._partial[path] = 0, b""
        if size == start:
            return []
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                chunk = fh.read(min(size - start, MAX_READ))
        except OSError:
            return []
        self._offsets[path] = start + len(chunk)
        data = self._partial.pop(path, b"") + chunk
        lines = data.split(b"\n")
        if lines[-1]:
            self._partial[path] = lines[-1]             # a line still being written
        return self._parse(lines[:-1])

    # ---- records ----------------------------------------------------------
    def _job_for(self, version: str, when: Optional[dt.datetime]):
        if self._jobs_for_version is None or when is None:
            return None
        cached = self._jobs.get(version)
        if cached is None or time.monotonic() - cached[0] > 5:
            try:
                jobs = list(self._jobs_for_version(version) or [])
            except Exception:                           # noqa: BLE001 - a log line is not worth a failure
                jobs = []
            self._jobs[version] = cached = (time.monotonic(), jobs)
        for job in cached[1]:
            started = _aware(getattr(job, "started_at", None))
            ended = _aware(getattr(job, "completed_at", None))
            if started and started <= when and (ended is None or when <= ended):
                return job
        return None

    def _prepare(self, rec: dict) -> dict:
        rec["message"] = self._mask(str(rec.get("message", "")))
        if rec.get("source") == "engine" and rec.get("version") and not rec.get("job"):
            job = self._job_for(rec["version"], _parse_ts(rec.get("ts")))
            if job is not None:
                rec["job"] = job.id
                rec["run"] = run_kind(getattr(job, "mode", None))
                # A process told only the version (the flowchart engine) gets it from its job.
                if not rec.get("project") and getattr(job, "project_id", None):
                    rec["project"] = job.project_id
        return rec

    def _append(self, records: List[dict]) -> None:
        records.sort(key=lambda r: _parse_ts(r.get("ts")) or dt.datetime.min.replace(
            tzinfo=dt.timezone.utc))
        with self._lock:
            for rec in records:
                self._seq += 1
                rec["seq"] = self._seq
                self._records.append(rec)

    def backfill(self) -> int:
        """Fill the buffer from the end of the newest files; later passes read only what is
        added after this."""
        every = self._files()
        for path in every[:-BACKFILL_FILES]:            # older files: only what they gain from now
            try:
                self._offsets[path] = os.path.getsize(path)
            except OSError:
                pass
        found: List[dict] = []
        for path in every[-BACKFILL_FILES:]:
            try:
                size = os.path.getsize(path)
                with open(path, "rb") as fh:
                    start = max(0, size - BACKFILL_BYTES)
                    fh.seek(start)
                    data = fh.read(size - start)
            except OSError:
                continue
            lines = data.split(b"\n")
            if start > 0:
                lines = lines[1:]                       # the first is cut
            self._offsets[path] = size
            if lines and lines[-1]:
                self._partial[path] = lines[-1]
            found.extend(self._parse(lines[:-1]))
        found.sort(key=lambda r: _parse_ts(r.get("ts")) or dt.datetime.min.replace(
            tzinfo=dt.timezone.utc))
        found = found[-self._records.maxlen:]
        self._append([self._prepare(r) for r in found])
        return len(found)

    def poll(self) -> int:
        """Read what every file gained since the last pass. Returns the records added."""
        batch: List[dict] = []
        for path in self._files():
            batch.extend(self._prepare(r) for r in self._read_new(path))
        if batch:
            self._append(batch)
        return len(batch)

    def cleanup(self, keep_days: int, today: Optional[dt.date] = None) -> int:
        """Delete day folders older than `keep_days`. Returns how many went."""
        today = today or dt.date.today()
        gone = 0
        try:
            names = os.listdir(self.root)
        except OSError:
            return 0
        for name in names:
            try:
                day = dt.date.fromisoformat(name)
            except ValueError:
                continue
            if (today - day).days > keep_days:
                shutil.rmtree(os.path.join(self.root, name), ignore_errors=True)
                gone += 1
        return gone

    # ---- reading the buffer -----------------------------------------------
    @staticmethod
    def matches(rec: dict, level: str, filters: Dict[str, Optional[str]]) -> bool:
        if LEVELS.get(str(rec.get("level")), 0) < LEVELS.get(level, 20):
            return False
        return all(not want or str(rec.get(key) or "") == want for key, want in filters.items())

    def tail(self, lines: int, level: str, filters: Dict[str, Optional[str]]
             ) -> Tuple[List[dict], int]:
        """The last `lines` matching records, oldest first, and the cursor (the last `seq`)."""
        with self._lock:
            records, cursor = list(self._records), self._seq
        out = []
        for rec in reversed(records):
            if self.matches(rec, level, filters):
                out.append(rec)
                if len(out) >= lines:
                    break
        return out[::-1], cursor

    def after(self, seq: int, level: str, filters: Dict[str, Optional[str]], limit: int = 1000
              ) -> Tuple[List[dict], int, bool]:
        """Matching records after `seq`, the new cursor, and whether records between `seq` and
        the oldest still kept were lost (the buffer moved past them)."""
        with self._lock:
            records, cursor = list(self._records), self._seq
        if not records:
            return [], cursor, False
        gap = seq < records[0]["seq"] - 1
        out = [r for r in records if r["seq"] > seq and self.matches(r, level, filters)]
        if len(out) > limit:
            out = out[:limit]
            cursor = out[-1]["seq"]
        return out, cursor, gap

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    # ---- the thread -------------------------------------------------------
    def run_forever(self, keep_days: Callable[[], int]) -> None:
        try:
            self.backfill()
        except Exception:                               # noqa: BLE001
            _log.exception("live log: could not read the existing files")
        while True:
            day = dt.date.today().isoformat()
            if day != self._cleaned_on:
                self._cleaned_on = day
                try:
                    self.cleanup(int(keep_days()))
                except Exception:                       # noqa: BLE001
                    pass
            try:
                self.poll()
            except Exception:                           # noqa: BLE001 - keep following
                pass
            time.sleep(POLL_SECONDS)

    def start(self, keep_days: Callable[[], int]) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self.run_forever, args=(keep_days,),
                                            daemon=True, name="live-log-reader")
            self._thread.start()


# ---------------------------------------------------------------------------
# The API's one reader
# ---------------------------------------------------------------------------
READER: Optional[LiveLogReader] = None


def get_reader() -> LiveLogReader:
    """The process's reader, created on first use (not started -- `start_reader` does that)."""
    global READER
    if READER is None:
        from core.logging_setup import live_log_root
        from ..db.session import _db
        jobs = getattr(_db, "jobs", None)
        READER = LiveLogReader(live_log_root(),
                               jobs_for_version=getattr(jobs, "list_for_version", None),
                               secrets=configured_secrets())
    return READER


def start_reader() -> Optional[LiveLogReader]:
    """Start following the files, unless the live log is off in this process (the tests)."""
    from core import logging_setup
    if not logging_setup.LIVE_LOG_ENABLED:
        return None
    from core.config import logs_config
    reader = get_reader()
    reader.start(lambda: logs_config()["keepDays"])
    return reader
