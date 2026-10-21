"""
Central settings — reads from environment variables.

Environment variables (all optional — defaults apply):

  ANALYZER_REPO_ROOT        Path to the repository root (contains engine/run.py).
                            Default: auto-detected relative to this file.
  ANALYZER_WORKSPACES_DIR   Where per-project checkout + output dirs live.
                            Default: <ANALYZER_REPO_ROOT>/workspaces/
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
    # How many jobs run at once is NOT a setting here any more: it is `jobs.maxGenerations` in
    # engine/config/config.local.json, counted in the database by the scheduler's claim, for every
    # process alike (docs/spec/JOB_SCHEDULING_SPEC.md REQ-JS-05). The `JOB_MAX_CONCURRENCY`
    # environment variable, which sized a semaphore inside one API process, is not read.
    #
    # !! LLM GATEWAY (doc 09 B6, STILL OPEN): the rate limit is PER PROCESS. The corporate
    # gateway allows ~1 call / 3s, and `llmServer.rateLimitSeconds` enforces that inside ONE job — so
    # N generations at once hit the gateway at ~N calls / 3s. Until a shared limiter exists, set
    # `llmServer.rateLimitSeconds` to 3 x `jobs.maxGenerations` so the AGGREGATE rate is right, use
    # the `speedups.llms` lanes, or point the runs at the on-prem hosted model (`rateLimitSeconds: 0`).
    subprocess_timeout: int = 0        # seconds; 0 = no limit (a run as a child of the API)
    # A run started from the web app runs in the BACKGROUND (`analyzer.py ... --detach`) when the
    # API has a database: it outlives an API restart, which follows it again. Off = a child of
    # the API, as before (it dies with the API). pipeline_runner `_execute_detached`.
    job_detach: bool = True

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
