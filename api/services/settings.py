"""
Central settings — reads from environment variables.

Environment variables (all optional — defaults apply):

  ANALYZER_REPO_ROOT        Path to the repository root (contains run.py).
                            Default: auto-detected relative to this file.
  ANALYZER_WORKSPACES_DIR   Where per-project checkout + output dirs live.
                            Default: <ANALYZER_REPO_ROOT>/workspaces/
  JOB_MAX_CONCURRENCY       Max pipeline subprocesses running simultaneously.
                            Default: 2
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
