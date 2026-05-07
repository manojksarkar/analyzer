"""Plan the analyzer phase sequence based on config + CLI flags.

Centralises the three-branch logic that used to live in run.py:

  - no layer in config       -> single run, all 4 phases
  - layer + no --selected    -> build model once, then phase 3+4
                                        for every group
  - layer + --selected GROUP -> build model once, then phase 3+4
                                        for that one group

Each branch produces a single, flat `RunPlan` whose `.phases` list is fed
straight to PhaseRunner.run(). The crash-recovery `--from-phase` flag is
translated here, in one place, instead of being smeared across the three
call sites with `max(1, from_phase - 2)` arithmetic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .orchestration import Phase
from .paths import paths


# Canonical phase indices used by --from-phase. These are the *user-visible*
# numbers; the planner translates them to runner-visible indices in the flat
# phase list it produces.
PHASE_PARSE = 1     # Phase 1: Parse C++ source         -> parser.py
PHASE_DERIVE = 2    # Phase 2: Derive model             -> model_deriver.py
PHASE_VIEWS = 3     # Phase 3: Generate views           -> run_views.py / run_add_views.py
PHASE_EXPORT = 4    # Phase 4: Export to DOCX           -> docx_exporter.py / architecture_docx_exporter.py

# Valid doc_type values for plan_runs().
DOC_TYPE_SDD  = "sdd"
DOC_TYPE_ADD  = "add"
DOC_TYPE_BOTH = "both"


@dataclass
class RunPlan:
    """A planned sequence of phases for a single PhaseRunner.run() call.

    `runner_from_phase` is the 1-based index inside `phases` to start at; the
    planner has already translated the user's `--from-phase` flag.
    """
    label: str
    phases: List[Phase] = field(default_factory=list)
    runner_from_phase: int = 1


def _resolve_group_name(groups: Dict[str, Any], requested: Optional[str]) -> Optional[str]:
    if not requested:
        return None
    if not isinstance(groups, dict) or not groups:
        return None
    if requested in groups:
        return requested
    req_key = requested.casefold()
    for k in groups.keys():
        if isinstance(k, str) and k.casefold() == req_key:
            return k
    return None


def _build_model_phases(
    project_path: str,
    *,
    no_llm_summarize: bool,
    layer_name: Optional[str] = None,
) -> List[Phase]:
    deriver_args = [] if no_llm_summarize else ["--llm-summarize"]
    parser_args = [project_path]
    if layer_name:
        parser_args += ["--layer", layer_name]
        deriver_args += ["--layer", layer_name]
    label_suffix = f" ({layer_name})" if layer_name else ""
    return [
        Phase(f"Phase 1: Parse C++ source{label_suffix}", "parser.py", parser_args),
        Phase(f"Phase 2: Derive model{label_suffix}", "model_deriver.py", deriver_args),
    ]


def _add_doc_phases(*, output_dir: Optional[str] = None) -> List[Phase]:
    """Phases 3+4 for the Architecture Design Document (runs once, no group loop)."""
    p = paths()
    if output_dir is None:
        output_dir = os.path.join(p.output_dir, "add")
    docx_path = os.path.join(p.output_dir, "Software Architecture Design Specification.docx")
    return [
        Phase("Phase 3: Generate ADD views", "run_add_views.py",
              ["--output-dir", output_dir]),
        Phase("Phase 4: Export Architecture Design Document", "architecture_docx_exporter.py",
              [output_dir, docx_path]),
    ]


def _view_export_phases(*, output_dir: Optional[str] = None,
                        selected_group: Optional[str] = None,
                        filter_mode: Optional[str] = None,
                        docx_args: Optional[List[str]] = None,
                        layer_name: Optional[str] = None) -> List[Phase]:
    views_args: List[str] = []
    if output_dir:
        views_args += ["--output-dir", output_dir]
    if selected_group:
        views_args += ["--selected-group", selected_group]
    if filter_mode:
        views_args += ["--filter-mode", filter_mode]
    if layer_name:
        views_args += ["--layer", layer_name]
    _docx_args = list(docx_args or [])
    if layer_name and "--layer" not in _docx_args:
        _docx_args += ["--layer", layer_name]
    return [
        Phase("Phase 3: Generate views", "run_views.py", views_args),
        Phase("Phase 4: Export to DOCX", "docx_exporter.py", _docx_args),
    ]


def plan_runs(
    cfg: Dict[str, Any],
    *,
    project_path: str,
    selected_group: Optional[str],
    use_model: bool,
    no_llm_summarize: bool,
    from_phase: int = 1,
    filter_mode: Optional[str],
    doc_type: str = DOC_TYPE_SDD,
) -> List[RunPlan]:
    """Translate config + CLI flags into a flat list of RunPlan objects.

    Each RunPlan maps to one PhaseRunner.run(...) call. Returning a *list*
    (not a single plan) lets us emit one plan per group while keeping the
    runner itself dead-simple.

    Raises ValueError if `selected_group` is set but doesn't exist in
    config.layer (caller is expected to translate this to a
    user-visible error).
    """
    p = paths()
    from .config import get_flat_groups
    groups_cfg = get_flat_groups(cfg)
    group_names = sorted(groups_cfg.keys()) if isinstance(groups_cfg, dict) else []

    resolved_selected = _resolve_group_name(groups_cfg, selected_group)
    if selected_group and not resolved_selected:
        raise ValueError(
            f"Unknown --selected-group {selected_group!r}. "
            f"Valid groups: {', '.join(group_names) if group_names else '(none)'}"
        )

    plans: List[RunPlan] = []

    generate_sdd = doc_type in (DOC_TYPE_SDD, DOC_TYPE_BOTH)
    generate_add = doc_type in (DOC_TYPE_ADD, DOC_TYPE_BOTH)

    # --selected-group only applies to SDD; flag it early when ADD-only.
    if selected_group and not generate_sdd:
        raise ValueError("--selected-group is only valid for SDD (doc-type sdd or both)")

    # Build layer -> [group] and group -> layer mappings
    from .config import layers_config
    layers_cfg = layers_config()
    group_to_layer: Dict[str, str] = {}
    for lname, lcfg in layers_cfg.items():
        for gname in (lcfg.get("groups") or {}):
            group_to_layer[gname] = lname

    # ------------------------------------------------------------------
    # No layer: single flat run, all 4 phases (backward compat)
    # ------------------------------------------------------------------
    if not group_names:
        if generate_sdd:
            if use_model:
                phases = _view_export_phases(filter_mode=filter_mode)
                translated = max(1, from_phase - 2)
                plans.append(RunPlan(label="single run (use-model)",
                                     phases=phases,
                                     runner_from_phase=translated))
            else:
                phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize) \
                         + _view_export_phases(filter_mode=filter_mode)
                plans.append(RunPlan(label="single run",
                                     phases=phases,
                                     runner_from_phase=from_phase))
        if generate_add:
            if not use_model and not generate_sdd:
                build_phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize)
                if from_phase <= 2:
                    plans.append(RunPlan(label="Build model (all modules)",
                                         phases=build_phases,
                                         runner_from_phase=from_phase))
            add_from = max(1, from_phase - 2) if from_phase >= PHASE_VIEWS else 1
            plans.append(RunPlan(label="Architecture Design Document",
                                 phases=_add_doc_phases(),
                                 runner_from_phase=add_from))
        return plans

    # ------------------------------------------------------------------
    # Layers present: build model per layer, then per-group view+export
    # ------------------------------------------------------------------
    target_groups = [resolved_selected] if resolved_selected else group_names

    # Which layers do the target groups belong to?
    target_layers = []
    seen_layers: set = set()
    for g in target_groups:
        ln = group_to_layer.get(g)
        if ln and ln not in seen_layers:
            target_layers.append(ln)
            seen_layers.add(ln)

    if not use_model and from_phase <= 2:
        if target_layers:
            # Per-layer model build
            for ln in target_layers:
                build_phases = _build_model_phases(
                    project_path, no_llm_summarize=no_llm_summarize, layer_name=ln)
                plans.append(RunPlan(label=f"Build model ({ln})",
                                     phases=build_phases,
                                     runner_from_phase=from_phase))
        else:
            # Fallback: no layer mapping, build once
            build_phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize)
            plans.append(RunPlan(label="Build model (all modules)",
                                 phases=build_phases,
                                 runner_from_phase=from_phase))

    if generate_sdd:
        for g in target_groups:
            ln = group_to_layer.get(g)
            group_out = os.path.join(p.output_dir, g)
            view_phases = _view_export_phases(
                output_dir=group_out,
                selected_group=g,
                filter_mode=filter_mode,
                layer_name=ln,
                docx_args=[
                    os.path.join(group_out, "interface_tables.json"),
                    os.path.join(group_out, f"software_detailed_design_{g}.docx"),
                    "--selected-group", g,
                ],
            )
            local_from = max(1, from_phase - 2) if from_phase >= PHASE_VIEWS else 1
            plans.append(RunPlan(label=f"Group: {g}",
                                 phases=view_phases,
                                 runner_from_phase=local_from))

    if generate_add:
        # ADD builds model for ALL layers (not just target_layers)
        if not use_model and from_phase <= 2:
            all_layers = [ln for ln in layers_cfg if ln not in seen_layers]
            for ln in all_layers:
                build_phases = _build_model_phases(
                    project_path, no_llm_summarize=no_llm_summarize, layer_name=ln)
                plans.append(RunPlan(label=f"Build model ({ln})",
                                     phases=build_phases,
                                     runner_from_phase=from_phase))
        add_from = max(1, from_phase - 2) if from_phase >= PHASE_VIEWS else 1
        plans.append(RunPlan(label="Architecture Design Document",
                             phases=_add_doc_phases(),
                             runner_from_phase=add_from))

    return plans
