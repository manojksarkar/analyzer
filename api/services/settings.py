"""
Central settings — reads from environment variables.

Environment variables (all optional — defaults apply):

  ANALYZER_REPO_ROOT        Path to the repository root (contains engine/run.py).
                            Default: auto-detected relative to this file.
  ANALYZER_WORKSPACES_DIR   Where per-project checkout + output dirs live.
                            Default: <ANALYZER_REPO_ROOT>/workspaces/
  JOB_MAX_CONCURRENCY       Max pipeline jobs running simultaneously IN THIS
                            PROCESS.  Default: 1  (see the field for why)
  SUBPROCESS_TIMEOUT        Seconds before a pipeline subprocess is killed.
                            0 = no limit.  Default: 0
  LIBCLANG_PATH             Path to libclang shared library, forwarded to
                            run.py subprocesses.  Default: "" (auto-detect).
  API_DB_BACKEND            "memory" or "json"  (also read by db/session.py).
                            Default: "memory"
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file lives at api/services/settings.py.
# parents[0] = api/services/, parents[1] = api/, parents[2] = analyzer/  Wait...
# Path(__file__).resolve().parent = the api/services/ directory
# .parent.parent                  = api/
# .parent.parent.parent           = analyzer/ (repo root)
# Using .parents on the DIRECTORY:
#   _THIS_DIR.parents[0] = api/
#   _THIS_DIR.parents[1] = analyzer/  <-- repo root
_THIS_DIR: Path = Path(__file__).resolve().parent          # api/services/
_DEFAULT_REPO_ROOT: Path = _THIS_DIR.parents[1]            # analyzer/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    # Repository and workspace layout
    analyzer_repo_root: Path = Field(default=_DEFAULT_REPO_ROOT)
    analyzer_workspaces_dir: Path | None = None

    # Pipeline execution limits
    #
    # Default 1 (doc 09, B0). Every run still writes the SHARED <repo>/model and
    # <repo>/output, and a full generation _rmtree_force()s the output dir
    # (incremental/generate.py) -- so two concurrent jobs delete each other's work.
    # Serialising is the only safe setting until B1 gives each job its own data root.
    #
    # Raised deliberately at B4, not left permissive by default: the failure mode is
    # silent corruption of a document someone may already have approved.
    #
    # NOTE (multi-node): this bounds a threading.BoundedSemaphore inside ONE API
    # process (pipeline_runner._get_semaphore). With N replicas the real ceiling is
    # N x this value -- a global limit needs a DB-backed lease, tracked as B0c.
    #
    # Raised 1 -> 2 on 2026-08-17. Memory is not the ceiling (500 GB server); 2 rather than the
    # eventual 4 because the concurrency machinery has never run on real work, so this halves
    # the blast radius while it is validated — and halves the gateway overshoot below. Go to 4
    # once a real batch at 2 is clean.
    #
    # Worth knowing before expecting a speedup: the LLM gateway is a GLOBAL ~1 call / 3s
    # ceiling, so concurrency cannot make LLM work faster in aggregate — the gain is confined
    # to parse, rendering and export. It disappears entirely if the run points at the on-prem
    # hosted model instead (rateLimitSeconds: 0), which is the higher-value change. Everything that made 1 mandatory is now fixed: each job owns
    # versions/<ver>/{model,output,config,parse,manifest} (doc 09 B1 + doc 10), the shared
    # caches are content-addressed with process-private temp files, the per-commit checkout is
    # locked, and `entities`/`content_blobs` inserts are conflict-tolerant (doc 10 H1 — that one
    # was near-certain to collide, not rare).
    #
    # !! LLM GATEWAY (doc 09 B6, STILL OPEN): the rate limit is PER PROCESS. The corporate
    # gateway allows ~1 call / 3s, and `llm.rateLimitSeconds` enforces that inside ONE job — so
    # 4 concurrent jobs hit the gateway at ~4 calls / 3s, four times its limit. Until a shared
    # limiter exists, either set `llm.rateLimitSeconds` to 3 x this value (6) so the AGGREGATE
    # rate is correct, or point the run at the on-prem hosted model, which has no limit
    # (`rateLimitSeconds: 0`). Concurrency with LLM enabled and a 3s per-process limit WILL
    # exceed the gateway.
    job_max_concurrency: int = 2
    subprocess_timeout: int = 0        # seconds; 0 = no limit

    # Toolchain paths forwarded to subprocesses
    libclang_path: str = ""

    # DB backend (mirrors the value read by db/session.py)
    api_db_backend: str = "memory"

    # ------------------------------------------------------------------
    # Derived properties — not read from env vars directly
    # ------------------------------------------------------------------

    @property
    def repo_root(self) -> Path:
        """Absolute path to the analyzer repository root."""
        return self.analyzer_repo_root

    @property
    def workspaces(self) -> Path:
        """Absolute path to the per-project workspaces directory."""
        return self.analyzer_workspaces_dir or (self.analyzer_repo_root / "workspaces")


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
