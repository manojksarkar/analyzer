"""A project's cores, and the core each of its layers is built for.

A core is one build of the firmware: its macros (the -D set), its data dictionary and its
compile commands (the include paths the build used). The engine reads them as `cores.<Core>`
and `layers.<Layer>.cores` (engine/core/config.py, engine/core/compile_commands.py): a layer's
files parse with its core's macros and include paths, and its units take its core's dictionary.

In a project::

    build_config["cores"] = [{"name": "Core1",
                              "macros": {"mode": "upload", "file_id", "file_name"}
                                        | {"mode": "manual", "defines": ["A=1", ...]} | None,
                              "data_dictionary": {"file_id", "file_name"} | None,
                              "compile_commands": {"file_id", "file_name"} | None}]
    architecture_layers[i]["core"] = "Core1" | None

A project created before cores holds one definitions file and one data dictionary for the whole
project (`build_config.preprocessor_definitions`, `build_config.data_dictionary`). It is read as
one core, `Core1`, that every layer uses - what those inputs always meant.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

LEGACY_CORE = "Core1"
INPUTS = ("macros", "data_dictionary", "compile_commands")


def _upload(ref: Any) -> Optional[dict]:
    """An upload reference `{file_id, file_name}`, or None."""
    if isinstance(ref, dict) and str(ref.get("file_id") or "").strip():
        return {"file_id": str(ref["file_id"]).strip(), "file_name": str(ref.get("file_name") or "")}
    return None


def _macros(ref: Any) -> Optional[dict]:
    """`{mode: upload, file_id, file_name}` or `{mode: manual, defines}` - or None when empty."""
    if not isinstance(ref, dict):
        return None
    if str(ref.get("mode") or "").lower() == "upload" or ("file_id" in ref and "defines" not in ref):
        up = _upload(ref)
        return {"mode": "upload", **up} if up else None
    defines = [str(d).strip() for d in (ref.get("defines") or []) if str(d).strip()]
    return {"mode": "manual", "defines": defines} if defines else None


def _layer_name(layer: Any) -> str:
    return str((layer or {}).get("name") or "").strip() if isinstance(layer, dict) else ""


def project_cores(build_config: Optional[dict],
                  architecture_layers: Optional[list]) -> Tuple[List[dict], Dict[str, Optional[str]]]:
    """`(cores, layer name -> the name of its core, or None)`, each core normalised to
    `{name, macros, data_dictionary, compile_commands}`."""
    bc = build_config or {}
    layers = [l for l in (architecture_layers or []) if _layer_name(l)]
    raw = bc.get("cores")
    if isinstance(raw, list):
        cores = []
        for c in raw:
            if not isinstance(c, dict) or not str(c.get("name") or "").strip():
                continue
            cores.append({"name": str(c["name"]).strip(),
                          "macros": _macros(c.get("macros")),
                          "data_dictionary": _upload(c.get("data_dictionary")),
                          "compile_commands": _upload(c.get("compile_commands"))})
        return cores, {_layer_name(l): (str(l.get("core") or "").strip() or None) for l in layers}

    macros, dd = _macros(bc.get("preprocessor_definitions")), _upload(bc.get("data_dictionary"))
    if not macros and not dd:
        return [], {_layer_name(l): None for l in layers}
    legacy = {"name": LEGACY_CORE, "macros": macros, "data_dictionary": dd, "compile_commands": None}
    return [legacy], {_layer_name(l): LEGACY_CORE for l in layers}


def core_problems(build_config: Optional[dict], architecture_layers: Optional[list]) -> List[str]:
    """What makes a project's cores unusable, one message each - the run would refuse it or read
    it wrongly: a core with no name or a name used twice, a layer naming a core that is not
    there, a data dictionary that is not CSV (the engine reads CSV only), compile commands that
    are not JSON."""
    raw = (build_config or {}).get("cores")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return ["`cores` must be a list of cores."]
    out: List[str] = []
    names: List[str] = []
    for i, c in enumerate(raw, 1):
        name = str((c or {}).get("name") or "").strip() if isinstance(c, dict) else ""
        if not name:
            out.append(f"Core {i} has no name.")
            continue
        if name.casefold() in (n.casefold() for n in names):
            out.append(f"Two cores are called {name}.")
        names.append(name)
        dd = _upload(c.get("data_dictionary"))
        if dd and PurePosixPath(dd["file_name"]).suffix.lower() != ".csv":
            out.append(f"{name}: the data dictionary must be a .csv file, not {dd['file_name']}.")
        cc = _upload(c.get("compile_commands"))
        if cc and PurePosixPath(cc["file_name"]).suffix.lower() != ".json":
            out.append(f"{name}: compile commands must be a compile_commands.json, not {cc['file_name']}.")
    # The engine matches a layer's core by its exact name (engine/core/config.validate_cores).
    for layer in architecture_layers or []:
        core = str((layer or {}).get("core") or "").strip() if isinstance(layer, dict) else ""
        if core and core not in names:
            out.append(f"Layer {_layer_name(layer)} uses core {core}, which the project does not have.")
    return out


def describe(core: dict) -> Dict[str, Optional[str]]:
    """The core's inputs as short labels: a file name, `N typed`, or None."""
    m = core.get("macros")
    macros = (m.get("file_name") or "uploaded file") if m and m["mode"] == "upload" else (
        f"{len(m['defines'])} typed" if m else None)
    dd, cc = core.get("data_dictionary"), core.get("compile_commands")
    return {"macros": macros,
            "data_dictionary": (dd or {}).get("file_name") or None,
            "compile_commands": (cc or {}).get("file_name") or None}
