"""Slim type/macro usage index assembly for incremental impact analysis (M1.2b).

The analyzer's call graph + global reads/writes already live in functions.json
(`callsIds`/`calledByIds`, `reads`/`writesGlobalIds`), and the transitive closure
is computed by reverse-BFS at impact time — so model/edges.json only stores the two
axes functions.json lacks: which functions USE each type and each macro.

`build_edges` is pure (no libclang) so it is unit-testable; parser.py collects the
raw per-function data from the AST and hands it here.
"""
from __future__ import annotations

from typing import Dict, List, Set


def build_edges(
    type_users: Dict[str, Set[str]],
    function_tokens: Dict[str, Set[str]],
    type_keys: Set[str],
    macro_keys: Set[str],
    func_key_to_fid: Dict[str, str],
) -> Dict[str, Dict[str, List[str]]]:
    """Invert raw per-function usage into ``{typeUsers, macroUsers}`` keyed by model fid.

    Args:
      type_users:       {type_qn -> set(internal func_key)} referencing it (from AST).
      function_tokens:  {internal func_key -> set(identifier token spellings)} (for macros).
      type_keys:        project type qns that have a hash — used to FILTER (so every
                        edges key cross-references a hashes.json key).
      macro_keys:       known macro keys, each ``name@relFile``.
      func_key_to_fid:  internal func_key -> model fid (component|unit|qn|params).

    Returns ``{"typeUsers": {qn: [fid...]}, "macroUsers": {macroKey: [fid...]}}`` with
    keys and value-lists sorted, for byte-stable output.
    """
    type_out: Dict[str, List[str]] = {}
    for qn, fkeys in type_users.items():
        if qn not in type_keys:                      # only project types that have a hash
            continue
        fids = sorted({func_key_to_fid[fk] for fk in fkeys if fk in func_key_to_fid})
        if fids:
            type_out[qn] = fids

    # macro NAME -> [full key(s)]; a name may (rarely) be #defined in >1 file.
    name_to_keys: Dict[str, List[str]] = {}
    for mk in macro_keys:
        name_to_keys.setdefault(mk.split("@", 1)[0], []).append(mk)

    macro_tmp: Dict[str, Set[str]] = {}
    for fkey, toks in function_tokens.items():
        fid = func_key_to_fid.get(fkey)
        if not fid:
            continue
        for name in toks.intersection(name_to_keys.keys()):  # macro names used in the body
            for mk in name_to_keys[name]:
                macro_tmp.setdefault(mk, set()).add(fid)
    macro_out = {mk: sorted(v) for mk, v in macro_tmp.items()}

    return {
        "typeUsers": {k: type_out[k] for k in sorted(type_out)},
        "macroUsers": {k: macro_out[k] for k in sorted(macro_out)},
    }
