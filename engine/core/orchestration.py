"""Phase orchestration: one place that runs the analyzer's phases as subprocesses.

Each phase is a small Python script in `engine/`. Historically run.py contained
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
import platform
import sys
import time
from dataclasses import dataclass, field
from typing import List, Sequence

from . import run_metrics
from .db import set_pipeline_status
from .logging_setup import get_logger
from .paths import paths
from .subprocess_util import log_stderr_tail, run_streaming

os_type = platform.system()

_log = get_logger("orchestration")

# Phase -> the progress word the UI shows (doc 09, C1 / D-17). Keyed by SCRIPT rather than
# the display name: the name is prose that gets reworded, the script filename is the phase's
# actual identity. A phase not listed here simply reports no status.
_PIPELINE_STATUS_BY_SCRIPT = {
    "parser.py":        "parsing",
    "model_deriver.py": "deriving",
    "run_views.py":     "viewing",
    "docx_exporter.py": "exporting",
}


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
        cmd = [sys.executable, os.path.join(src_dir, self.script), *self.args]
        # Forward a relocated model dir to the phase (doc 09, C11b). Every phase reads
        # model_dir from paths() in its OWN process, so an override set in run.py would not
        # otherwise reach it. Appended here rather than in group_planner because this is the
        # single place every phase command is built — a per-dispatch-shape edit would silently
        # miss one. Only when an override is active, so a default run's argv is unchanged.
        from .paths import _OVERRIDE_MODEL_DIR, _OVERRIDE_OUTPUT_DIR
        if _OVERRIDE_MODEL_DIR:
            cmd += ["--model-root", _OVERRIDE_MODEL_DIR]
        # --output-root too. It was omitted on the reasoning that group_planner already bakes
        # an absolute --output-dir into each phase's args, which is true for WRITING — but the
        # incremental views also need to know the run's output ROOT, to work out which slot a
        # diagram occupies inside it and find the same slot in the baseline version. Without
        # it `paths().output_dir` in the phase is the DEFAULT root, the baseline lookup
        # resolves to nothing, and carry-forward silently does nothing: an incremental run
        # then regenerates only the affected units and never reproduces the rest, so most
        # diagrams are simply absent from the version's output and from the document.
        if _OVERRIDE_OUTPUT_DIR:
            cmd += ["--output-root", _OVERRIDE_OUTPUT_DIR]
        # And the run identity (doc 10, step 3). A phase is a separate process that starts
        # knowing nothing; once the model is in the database it must be told WHICH version it
        # is working on, because "whatever is in model/" no longer exists. Only appended when
        # set, so a plain file run's argv is unchanged.
        from .run_context import version_id, project_id, model_store_kind
        if version_id():
            cmd += ["--version-id", version_id()]
        if project_id():
            cmd += ["--project-id", project_id()]
        if model_store_kind() != "files":
            cmd += ["--model-store", model_store_kind()]
        return cmd


class PhaseRunner:
    """Run a sequence of Phase objects as subprocesses, in order.

    On the first non-zero return code the runner raises SystemExit with that
    code, matching the previous behaviour of run.py.
    """

    def __init__(self, *, project_root: str | None = None) -> None:
        p = paths()
        self.project_root = project_root or p.project_root
        self.src_dir = p.src_dir

    def run(self, phases: Sequence[Phase], *, from_phase: int = 1,
            on_phase_done=None) -> float:
        """Run a list of phases. Returns total elapsed seconds.

        Phases with 1-based index < from_phase are skipped (crash recovery).

        `on_phase_done(phase)` is called after each phase **succeeds** (doc 09, C11a). This is
        how the model reaches Postgres at every phase boundary instead of only at the end of
        the run: `engine/core/` is the bottom of the dependency graph and cannot import the
        store, so it defines the hook and `run.py` — which may import anything — supplies the
        implementation. A failure inside the callback is logged and does not fail the phase,
        because during the dual-write the files are still authoritative.
        """
        total = 0.0
        for idx, phase in enumerate(phases, start=1):
            if idx < from_phase:
                _log.info(f"[{idx}/{len(phases)}] {phase.name} — skipped (--from-phase {from_phase})")
                continue
            _log.info(f"[{idx}/{len(phases)}] === {phase.name} ===")
            # Live progress on the version row (doc 09, C1). No-op without a version id
            # or a database, so CLI runs and the DB-less gate are unaffected.
            set_pipeline_status(_PIPELINE_STATUS_BY_SCRIPT.get(phase.script, ""))
            t0 = time.perf_counter()
            # stderr is streamed through (the API tails it for job progress) with
            # only its tail retained, so a failure can say WHY (doc 09, A0), and
            # the child's process tree is sampled for peak RSS (doc 09, D2a).
            returncode, stderr_tail, peak_rss_mb = run_streaming(
                phase.command(self.src_dir),
                cwd=self.project_root,
                shell=(os_type == "Windows"),
                sample_rss=True,
            )
            elapsed = time.perf_counter() - t0
            total += elapsed
            rss_note = f", peak RSS {peak_rss_mb:.0f} MB" if peak_rss_mb else ""
            _log.info(f"[{idx}/{len(phases)}] {phase.name} — {elapsed:.2f}s{rss_note}")
            run_metrics.record_phase(
                phase.name,
                elapsed_sec=elapsed,
                returncode=returncode,
                peak_rss_mb=peak_rss_mb,
                script=phase.script,
            )
            if returncode != 0:
                log_stderr_tail(phase.name, stderr_tail, logger=_log)
                _log.error(
                    f"{phase.name} failed with exit code {returncode}; "
                    f"resume with: --from-phase {idx}"
                )
                raise SystemExit(returncode)
            if on_phase_done is not None:
                try:
                    on_phase_done(phase)
                except Exception as exc:            # dual-write: files are still the source
                    _log.error(f"{phase.name}: post-phase hook failed: "
                               f"{type(exc).__name__}: {exc}")
        return total
