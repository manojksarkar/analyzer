"""Plan the analyzer phase sequence based on config + CLI flags.

Centralises the three-branch logic that used to live in run.py:

  - no modulesGroups in config       -> single run, all 4 phases
  - modulesGroups + no --selected    -> build model once, then phase 3+4
                                        for every group
  - modulesGroups + --selected GROUP -> build model once, then phase 3+4
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
PHASE_VIEWS = 3     # Phase 3: Generate views           -> run_views.py
PHASE_EXPORT = 4    # Phase 4: Export to DOCX           -> docx_exporter.py


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


def _build_model_phases(project_path: str, *, no_llm_summarize: bool) -> List[Phase]:
    deriver_args = [] if no_llm_summarize else ["--llm-summarize"]
    return [
        Phase("Phase 1: Parse C++ source", "parser.py", [project_path]),
        Phase("Phase 2: Derive model", "model_deriver.py", deriver_args),
    ]


def _view_export_phases(*, output_dir: Optional[str] = None,
                        selected_group: Optional[str] = None,
                        docx_args: Optional[List[str]] = None) -> List[Phase]:
    views_args: List[str] = []
    if output_dir:
        views_args += ["--output-dir", output_dir]
    if selected_group:
        views_args += ["--selected-group", selected_group]
    return [
        Phase("Phase 3: Generate views", "run_views.py", views_args),
        Phase("Phase 4: Export to DOCX", "docx_exporter.py", list(docx_args or [])),
    ]


def plan_runs(
    cfg: Dict[str, Any],
    *,
    project_path: str,
    selected_group: Optional[str],
    use_model: bool,
    no_llm_summarize: bool,
    from_phase: int = 1,
) -> List[RunPlan]:
    """Translate config + CLI flags into a flat list of RunPlan objects.

    Each RunPlan maps to one PhaseRunner.run(...) call. Returning a *list*
    (not a single plan) lets us emit one plan per group while keeping the
    runner itself dead-simple.

    Raises ValueError if `selected_group` is set but doesn't exist in
    config.modulesGroups (caller is expected to translate this to a
    user-visible error).
    """
    p = paths()
    groups_cfg = (cfg.get("modulesGroups") or {})
    group_names = sorted(groups_cfg.keys()) if isinstance(groups_cfg, dict) else []

    resolved_selected = _resolve_group_name(groups_cfg, selected_group)
    if selected_group and not resolved_selected:
        raise ValueError(
            f"Unknown --selected-group {selected_group!r}. "
            f"Valid groups: {', '.join(group_names) if group_names else '(none)'}"
        )

    plans: List[RunPlan] = []

    # ------------------------------------------------------------------
    # No modulesGroups: single flat run, all 4 phases
    # ------------------------------------------------------------------
    if not group_names:
        if use_model:
            # Skip phases 1+2; runner indices 1,2 map to phases 3,4
            phases = _view_export_phases()
            translated = max(1, from_phase - 2)
            plans.append(RunPlan(label="single run (use-model)",
                                 phases=phases,
                                 runner_from_phase=translated))
        else:
            phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize) \
                     + _view_export_phases()
            plans.append(RunPlan(label="single run",
                                 phases=phases,
                                 runner_from_phase=from_phase))
        return plans

    # ------------------------------------------------------------------
    # modulesGroups present: build model once, then per-group view+export
    # ------------------------------------------------------------------
    target_groups = [resolved_selected] if resolved_selected else group_names

    if not use_model:
        # Build-model plan covers phases 1+2 only.
        build_phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize)
        # If the user wants to start at phase >= 3, the build step is skipped
        # entirely (use existing model on disk).
        if from_phase <= 2:
            plans.append(RunPlan(label="Build model (all modules)",
                                 phases=build_phases,
                                 runner_from_phase=from_phase))

    for g in target_groups:
        # All groups get a fresh output sub-directory under output/<group>/.
        # When a single group is selected and resolves the same as today's
        # behaviour, run_views/docx_exporter handle output paths themselves
        # via --selected-group, so we don't pass --output-dir explicitly.
        if resolved_selected:
            view_phases = _view_export_phases(selected_group=g,
                                              docx_args=["--selected-group", g])
        else:
            group_out = os.path.join(p.output_dir, g)
            view_phases = _view_export_phases(
                output_dir=group_out,
                selected_group=g,
                docx_args=[
                    os.path.join(group_out, "interface_tables.json"),
                    os.path.join(group_out, f"software_detailed_design_{g}.docx"),
                    "--selected-group", g,
                ],
            )

        # When --from-phase points at views/export, translate it to the
        # group plan's local indices (which only contain phases 3+4).
        if from_phase >= PHASE_VIEWS:
            local_from = max(1, from_phase - 2)  # 3 -> 1, 4 -> 2
        else:
            local_from = 1
        plans.append(RunPlan(label=f"Group: {g}",
                             phases=view_phases,
                             runner_from_phase=local_from))

    return plans
