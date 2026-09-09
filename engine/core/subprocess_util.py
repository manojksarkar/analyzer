"""Subprocess execution that never loses a failed child's stderr (doc 09, A0).

Every pipeline phase, the flowchart engine, and the diagram renderers run as
child processes. Historically a failure logged only ``exited with code 1`` and
the child's traceback went nowhere -- the bug class that once hid a libclang
``LibclangError`` for an entire debugging session (PROJECT_CONTEXT §16 Risk 5).

The rule this module encodes: **never discard a failed child's stderr.**

It *streams* rather than buffers, for two reasons that both matter here:

  - The API derives job progress by tailing the merged output of ``run.py``
    (``pipeline_runner`` watches for ``=== Phase N: ===`` markers). Capturing
    stderr wholesale would cut that off and freeze the UI's progress bar.
  - A phase on a large codebase can emit tens of MB. Holding that in memory to
    print it once would be a real cost on a box already running several jobs.

So stderr is echoed through line by line and only the last ``tail_lines`` are
retained -- a bounded deque, so a chatty phase cannot grow memory.

Peak RSS sampling rides along because this is the only place that holds the
child's PID (doc 09, D2a). It is diagnostics: if ``psutil`` is missing or a
sample fails, the number comes back ``None`` and nothing else changes.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections import deque
from typing import List, Optional, Sequence, Tuple

from .logging_setup import get_logger

_log = get_logger("subprocess")

try:                                    # optional: diagnostics must not be a hard dep
    import psutil
except Exception:                       # pragma: no cover - depends on the install
    psutil = None                       # type: ignore[assignment]

DEFAULT_TAIL_LINES = 50


def echo_stderr(line: str) -> None:
    """Write one child line to our stderr, surviving a cp1252 console.

    PROJECT_CONTEXT §18: Windows stderr defaults to cp1252, and a single
    non-ASCII byte raises ``UnicodeEncodeError`` mid-run. Source comments in this
    domain legitimately contain non-ASCII (Korean has come up), so the pass-through
    must degrade rather than raise -- a logging helper must never be the thing that
    kills a pipeline.
    """
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except UnicodeEncodeError:
        try:
            sys.stderr.write(line.encode("ascii", "replace").decode("ascii"))
            sys.stderr.flush()
        except Exception:
            pass
    except Exception:
        pass


class _RssSampler(threading.Thread):
    """Track the peak RSS of a process *tree* (doc 09, D2a).

    The tree, not just the direct child: on Windows we spawn through a shell, so
    the real interpreter is one level down, and a phase legitimately spawns the
    flowchart engine and Chromium beneath itself. Sampling only the handle we hold
    would report near-zero and be worse than not measuring at all.

    Known limitation, measured: polling cannot see a process that allocates and
    exits inside one interval, so a very short child under-reports. Irrelevant for
    the thing we are sizing — phases run for minutes — but do not reuse this to
    measure something brief without shrinking ``interval``.
    """

    def __init__(self, pid: int, interval: float) -> None:
        super().__init__(name="rss-sampler", daemon=True)
        self._pid = pid
        self._interval = interval
        # NOT `self._stop` — threading.Thread already defines a private _stop()
        # method, and shadowing it with an Event breaks Thread.join().
        self._halt = threading.Event()
        self.peak_bytes = 0

    def run(self) -> None:
        try:
            root = psutil.Process(self._pid)
        except Exception:
            return
        while not self._halt.is_set():
            total = 0
            try:
                procs = [root] + root.children(recursive=True)
            except Exception:
                break                       # tree gone: the process exited, we're done
            for p in procs:
                try:
                    total += p.memory_info().rss
                except Exception:
                    continue                # a child exiting mid-sample is normal
            if total > self.peak_bytes:
                self.peak_bytes = total
            self._halt.wait(self._interval)

    def stop(self) -> None:
        self._halt.set()
        self.join(timeout=2)


def run_streaming(
    cmd: Sequence[str],
    *,
    cwd: Optional[str] = None,
    shell: bool = False,
    tail_lines: int = DEFAULT_TAIL_LINES,
    timeout: Optional[float] = None,
    sample_rss: bool = False,
    sample_interval: float = 0.5,
) -> Tuple[int, List[str], Optional[float]]:
    """Run ``cmd``, echoing its stderr through while retaining the last lines.

    Returns ``(returncode, stderr_tail, peak_rss_mb)``. ``peak_rss_mb`` is ``None``
    when sampling is off or ``psutil`` is unavailable.

    ``subprocess.TimeoutExpired`` propagates after the child is killed, so callers
    that already handle it keep working unchanged.
    """
    tail: deque = deque(maxlen=max(1, tail_lines))
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        shell=shell,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def _pump() -> None:
        try:
            for line in proc.stderr:        # type: ignore[union-attr]
                tail.append(line.rstrip("\r\n"))
                echo_stderr(line)
        except Exception:
            pass

    pump = threading.Thread(target=_pump, name="stderr-pump", daemon=True)
    pump.start()

    sampler = _RssSampler(proc.pid, sample_interval) if (sample_rss and psutil) else None
    if sampler is not None:
        sampler.start()

    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        if sampler is not None:
            sampler.stop()
        pump.join(timeout=5)                # the pipe closes when the child exits
        try:
            if proc.stderr:
                proc.stderr.close()
        except Exception:
            pass

    peak_mb = None
    if sampler is not None and sampler.peak_bytes:
        peak_mb = round(sampler.peak_bytes / (1024 * 1024), 1)
    return rc, list(tail), peak_mb


def log_stderr_tail(label: str, tail: Sequence[str], *, logger=None) -> None:
    """Log a failed child's retained stderr, attributed to what failed.

    Emitted immediately before the caller's own failure line so the cause and the
    exit code sit together in ``logs/run_<date>.log`` instead of being separated by
    whatever else was interleaving on the console.
    """
    if not tail:
        return
    lg = logger or _log
    lg.error("---- %s: last %d line(s) of stderr ----", label, len(tail))
    for line in tail:
        lg.error("  %s", line)
    lg.error("---- end %s stderr ----", label)
