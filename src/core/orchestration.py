"""Phase orchestration: one place that runs the analyzer's phases as subprocesses.

Each phase is a small Python script in `src/`. Historically run.py contained
three branches that each hand-built `subprocess.run([sys.executable, ...])`
argv lists, captured elapsed time, logged the result, and propagated exit
codes. This module collapses that into:

  - Phase  : a frozen dataclass describing one phase invocation
  - PhaseRunner.run(phases, from_phase=1) : sequential subprocess execution

Crash-recovery semantics are preserved: pass `from_phase=N` (1-based against
the phases list you supply) and any phase whose 1-based index is < N is
skipped. The planner (group_planner.py) translates the user-supplied
`--from-phase` once at plan time so the runner just sees a flat list.

Logging goes through core.logging_setup, which means the daily log file
captures every phase header and elapsed time.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Sequence
from utils import os_type
from .logging_setup import get_logger
from .paths import paths

_log = get_logger("orchestration")


@dataclass(frozen=True)
class Phase:
    """One phase invocation.

    Attributes:
        name:   human-readable label, e.g. "Phase 1: Parse C++ source"
        script: filename relative to src/, e.g. "parser.py"
        args:   list of CLI arguments to pass after the script path
    """
    name: str
    script: str
    args: List[str] = field(default_factory=list)

    def command(self, src_dir: str) -> List[str]:
        return [sys.executable, os.path.join(src_dir, self.script), *self.args]


class PhaseRunner:
    """Run a sequence of Phase objects as subprocesses, in order.

    On the first non-zero return code the runner raises SystemExit with that
    code, matching the previous behaviour of run.py.
    """

    def __init__(self, *, project_root: str | None = None) -> None:
        p = paths()
        self.project_root = project_root or p.project_root
        self.src_dir = p.src_dir

    def run(self, phases: Sequence[Phase], *, from_phase: int = 1) -> float:
        """Run a list of phases. Returns total elapsed seconds.

        Phases with 1-based index < from_phase are skipped (crash recovery).
        """
        total = 0.0
        for idx, phase in enumerate(phases, start=1):
            if idx < from_phase:
                _log.info(f"[{idx}/{len(phases)}] {phase.name} — skipped (--from-phase {from_phase})")
                continue
            _log.info(f"[{idx}/{len(phases)}] === {phase.name} ===")
            t0 = time.perf_counter()
            if os_type == "Windows":
                r = subprocess.run(
                    phase.command(self.src_dir),
                    cwd=self.project_root, shell=True
                )
            else:
                r = subprocess.run(
                    phase.command(self.src_dir),
                    cwd=self.project_root,
                )
            elapsed = time.perf_counter() - t0
            total += elapsed
            _log.info(f"[{idx}/{len(phases)}] {phase.name} — {elapsed:.2f}s")
            if r.returncode != 0:
                _log.error(
                    f"{phase.name} failed with exit code {r.returncode}; "
                    f"resume with: --from-phase {idx}"
                )
                raise SystemExit(r.returncode)
        return total
