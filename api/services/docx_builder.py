"""
DOCX builder — calls ``src/docx_exporter.export_docx`` in a subprocess and
returns the resulting ``.docx`` file as bytes.

Why subprocess instead of a direct import?
------------------------------------------
``docx_exporter.py`` uses ``from utils import …`` (a bare-module import that
assumes ``src/`` is on ``sys.path``) and calls ``from core.paths import paths``
which resolves ``project_root`` from ``__file__`` location.  Importing it
inside the API process would require careful sys.path surgery and would pollute
the process namespace.  A tiny launcher script is cleaner and keeps the
pipeline's import assumptions intact.

Launcher script
---------------
``api/services/_docx_launcher.py`` is written once on first use.  It sets up
``sys.path``, imports ``export_docx``, and writes the output path to stdout.

Calling convention
------------------
``build_docx(group, project_path, docx_out_path, timeout)``

Returns
-------
``(ok: bool, path: Path | None, error: str | None)``

When ``ok`` is True, the caller can read ``path`` and stream it to the client.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Launcher script — written once to a temp location inside the repo
# ---------------------------------------------------------------------------

_LAUNCHER_PATH = Path(__file__).resolve().parent / "_docx_launcher.py"
_LAUNCHER_SRC = textwrap.dedent("""\
    \"\"\"
    Thin wrapper that imports export_docx from src/docx_exporter and calls it.
    Argv: <project_root> <group_or_empty> <docx_out_path> [<selected_component>...]
    \"\"\"
    import sys
    import os

    project_root = sys.argv[1]
    group        = sys.argv[2] or None
    docx_out     = sys.argv[3]
    components   = sys.argv[4:] if len(sys.argv) > 4 else []

    # Put src/ on the path so bare `from utils import …` works.
    src_dir = os.path.join(project_root, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    # Also put project_root so `from core …` resolves.
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Force run.py cwd semantics so paths.py finds the right root.
    os.chdir(project_root)

    from docx_exporter import export_docx

    selected_components = components if components else None
    ok, out_path = export_docx(
        docx_path=docx_out,
        selected_group=group if not selected_components else None,
        selected_components=selected_components,
    )
    if ok and out_path:
        print(out_path)
        sys.exit(0)
    else:
        sys.exit(1)
""")


def _ensure_launcher() -> Path:
    """Write the launcher script if it doesn't exist yet."""
    if not _LAUNCHER_PATH.exists():
        _LAUNCHER_PATH.write_text(_LAUNCHER_SRC, encoding="utf-8")
    return _LAUNCHER_PATH


def _find_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        if (candidate / "run.py").exists():
            return candidate
    return here.parent.parent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_docx(
    group: str = "",
    selected_components: Optional[list[str]] = None,
    project_path: Optional[str] = None,
    docx_out_path: Optional[str] = None,
    timeout: int = 120,
) -> Tuple[bool, Optional[Path], Optional[str]]:
    """
    Run ``export_docx`` and return ``(ok, path, error)``.

    Parameters
    ----------
    group
        Group name (e.g. ``"Chassis_Mgmt"``).  Empty = all groups.
    selected_components
        List of component names; mutually exclusive with *group*.
    project_path
        Path to the C++ source tree.  Defaults to ``SampleCppProject/``
        under the repo root (the test corpus).
    docx_out_path
        Where to write the ``.docx``.  Defaults to
        ``<root>/output/software_detailed_design_<group>.docx``.
    timeout
        Seconds before the subprocess is killed.

    Returns
    -------
    (True, Path, None)    — success; Path points to the written file.
    (False, None, str)    — failure; str is the error message.
    """
    root = _find_root()
    launcher = _ensure_launcher()

    if project_path is None:
        # Default to the bundled test corpus if it exists
        default = root / "SampleCppProject"
        project_path = str(default) if default.is_dir() else str(root)

    group_arg = group or ""
    if not docx_out_path:
        group_name = "_".join(selected_components) if selected_components else (group or "all")
        docx_out_path = str(root / "output" / f"software_detailed_design_{group_name}.docx")

    cmd = [
        sys.executable, str(launcher),
        str(root),          # project_root (where run.py lives — not the cpp source)
        group_arg,
        docx_out_path,
    ]
    if selected_components:
        cmd.extend(selected_components)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return False, None, f"DOCX export timed out after {timeout}s."
    except Exception as exc:
        return False, None, str(exc)

    if result.returncode == 0:
        out = result.stdout.strip()
        path = Path(out) if out else Path(docx_out_path)
        if path.exists():
            return True, path, None
        return False, None, f"export_docx reported success but file not found: {path}"

    # Failure — collect error from stderr
    err = (result.stderr or result.stdout or "export_docx failed").strip()
    return False, None, err[-500:]   # cap at 500 chars


def list_docx_outputs(group: str = "") -> list[Path]:
    """
    Return all ``.docx`` files in ``<root>/output/`` matching *group*.

    If *group* is empty, returns all ``.docx`` files.
    """
    root = _find_root()
    output_dir = root / "output"
    if not output_dir.is_dir():
        return []
    pattern = f"*{group}*.docx" if group else "*.docx"
    return sorted(output_dir.glob(pattern))
