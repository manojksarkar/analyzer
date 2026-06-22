"""Baseline selection for incremental generation (doc 04 §6, D4).

Default = **auto nearest-ancestor**: among prior *complete* versions' commits, the
nearest ancestor of the target. None → FULL generation. The user may **override**
with a versionId; we warn (but still run) if it is not an ancestor ("divergent
base" — close to a full gen) or not the nearest (a faster base exists).

Correctness is base-independent — the base only narrows the parse; reuse is
content-addressed. So a "wrong" base is *slow, never stale*.

Pure of any storage: takes the version list (from VersionStore) + a repo dir, and
uses git_ops for ancestry. Returns a plain dict matching doc 05 §5.1's preview.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from incremental import git_ops


def _complete(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [v for v in versions if v.get("status") == "complete" and v.get("commit")]


def _version_at(versions: List[Dict[str, Any]], commit: str) -> Optional[Dict[str, Any]]:
    """Newest complete version whose commit == `commit` (versions are newest-first)."""
    for v in _complete(versions):
        if v.get("commit") == commit:
            return v
    return None


def select_baseline(repo_dir: str,
                    versions: List[Dict[str, Any]],
                    target_commit: str,
                    override_version_id: Optional[str] = None) -> Dict[str, Any]:
    """Return the baseline decision for generating `target_commit`.

    Keys (doc 05 §5.1): targetCommit, autoBaselineVersionId, autoBaselineCommit,
    chosenBaseVersionId, chosenBaseCommit, chosenIsAncestor, chosenIsNearest,
    changedFiles, decision ("incremental"|"full"), warnings[].
    """
    candidates = _complete(versions)
    auto_commit = git_ops.nearest_ancestor(repo_dir, [v["commit"] for v in candidates], target_commit)
    auto_version = _version_at(versions, auto_commit) if auto_commit else None
    auto_vid = auto_version["versionId"] if auto_version else None

    warnings: List[str] = []

    # No override: take the auto nearest-ancestor (or full when none).
    if not override_version_id:
        decision = "incremental" if auto_commit else "full"
        changed = (len(git_ops.changed_files(repo_dir, auto_commit, target_commit))
                   if auto_commit else None)
        return _result(target_commit, auto_vid, auto_commit, auto_vid, auto_commit,
                       chosen_is_ancestor=bool(auto_commit), chosen_is_nearest=bool(auto_commit),
                       changed=changed, decision=decision, warnings=warnings)

    # Override: locate the chosen version, validate, warn as needed.
    chosen = next((v for v in versions if v.get("versionId") == override_version_id), None)
    if chosen is None or chosen.get("status") != "complete":
        why = "not found" if chosen is None else "is not complete"
        warnings.append(f"baseVersionId {override_version_id!r} {why}; using auto baseline")
        res = select_baseline(repo_dir, versions, target_commit)
        res["warnings"] = warnings + res["warnings"]
        return res

    chosen_commit = chosen.get("commit")
    is_anc = git_ops.is_ancestor(repo_dir, chosen_commit, target_commit)
    is_nearest = bool(auto_commit) and chosen_commit == auto_commit
    if not is_anc:
        warnings.append(
            f"base {override_version_id} is not an ancestor of the target - this run will be "
            f"close to a FULL generation (correct, but slower)")
    elif not is_nearest and auto_vid:
        warnings.append(
            f"base {override_version_id} is an ancestor but not the nearest ({auto_vid}); "
            f"{auto_vid} will be faster")
    changed = len(git_ops.changed_files(repo_dir, chosen_commit, target_commit))
    return _result(target_commit, auto_vid, auto_commit, override_version_id, chosen_commit,
                   chosen_is_ancestor=is_anc, chosen_is_nearest=is_nearest,
                   changed=changed, decision="incremental", warnings=warnings)


def _result(target, auto_vid, auto_commit, chosen_vid, chosen_commit,
            *, chosen_is_ancestor, chosen_is_nearest, changed, decision, warnings) -> Dict[str, Any]:
    return {
        "targetCommit": target,
        "autoBaselineVersionId": auto_vid,
        "autoBaselineCommit": auto_commit,
        "chosenBaseVersionId": chosen_vid,
        "chosenBaseCommit": chosen_commit,
        "chosenIsAncestor": chosen_is_ancestor,
        "chosenIsNearest": chosen_is_nearest,
        "changedFiles": changed,
        "decision": decision,
        "warnings": warnings,
    }
