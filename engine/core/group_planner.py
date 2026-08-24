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
from typing import Any, Dict, List, Optional, Tuple

from .orchestration import Phase
from .paths import paths


# Canonical phase indices used by --from-phase. These are the *user-visible*
# numbers; the planner translates them to runner-visible indices in the flat
# phase list it produces.
PHASE_PARSE = 1     # Phase 1: Parse C++ source   -> parser.py
PHASE_DERIVE = 2    # Phase 2: Derive model       -> model_deriver.py
PHASE_VIEWS = 3     # Phase 3: Generate views     -> run_views.py
PHASE_EXPORT = 4    # Phase 4: Export to DOCX     -> docx_exporter.py

# Valid doc_type values for plan_runs().
DOC_TYPE_SWE3 = "swe3"   # Software Detailed Design (existing default doc type)
DOC_TYPE_SWE2 = "swe2"   # Software Architecture Design (layer + component diagrams)
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


def _build_model_phases(project_path: str, *, no_llm_summarize: bool,
                        data_dictionary_path: Optional[str] = None,
                        data_dictionary_layer: Optional[List[Tuple[str, str]]] = None,
                        macros_path: Optional[str] = None,
                        macros_layer: Optional[List[Tuple[str, str]]] = None,
                        selected_group: Optional[str] = None,
                        selected_layer: Optional[str] = None,
                        project_name: Optional[str] = None,
                        only_files: Optional[str] = None,
                        include_emulator: bool = False) -> List[Phase]:
    deriver_args = [] if no_llm_summarize else ["--llm-summarize"]
    parser_args = [project_path]
    if data_dictionary_path:
        parser_args += ["--data-dictionary", data_dictionary_path]
    for _layer, _path in (data_dictionary_layer or []):
        parser_args += ["--data-dictionary-layer", _layer, _path]
    if macros_path:
        parser_args += ["--macros", macros_path]
    for _layer, _path in (macros_layer or []):
        parser_args += ["--macros-layer", _layer, _path]
    if selected_group:
        parser_args += ["--selected-group", selected_group]
    elif selected_layer:
        parser_args += ["--selected-layer", selected_layer]
    if project_name:
        parser_args += ["--project-name", project_name]
    if only_files:  # narrowed parse (M4.4): parser parses only the listed TUs
        parser_args += ["--only-files", only_files]
    if include_emulator:  # opt out of the default *emul* file exclusion (3.1)
        parser_args += ["--include-emulator"]
    return [
        Phase("Phase 1: Parse C++ source", "parser.py", parser_args),
        Phase("Phase 2: Derive model", "model_deriver.py", deriver_args),
    ]


def _view_export_phases(*, output_dir: Optional[str] = None,
                        selected_group: Optional[str] = None,
                        filter_mode: Optional[str] = None,
                        extra_view_args: Optional[List[str]] = None,
                        docx_args: Optional[List[str]] = None,
                        selected_units: Optional[List[str]] = None) -> List[Phase]:
    views_args: List[str] = []
    if output_dir:
        views_args += ["--output-dir", output_dir]
    if selected_group:
        views_args += ["--selected-group", selected_group]
    if filter_mode:
        views_args += ["--filter-mode", filter_mode]
    for _unit in (selected_units or []):
        views_args += ["--selected-unit", _unit]
    if extra_view_args:
        views_args += extra_view_args
    return [
        Phase("Phase 3: Generate views", "run_views.py", views_args),
        Phase("Phase 4: Export to DOCX", "docx_exporter.py", list(docx_args or [])),
    ]


def _swe2_doc_phases(*, output_dir: Optional[str] = None) -> List[Phase]:
    """Phases 3+4 for the SWE.2 Architecture Design doc (runs once, no group loop).

    Whole-model, not per-group — the SAD views cover every configured layer
    regardless of --selected-group/--selected-layer/--selected-component.
    """
    p = paths()
    if output_dir is None:
        output_dir = os.path.join(p.output_dir, "swe2")
    docx_path = os.path.join(p.output_dir, "Software Architecture Design Specification.docx")
    return [
        Phase("Phase 3: Generate SWE.2 (SAD) views", "run_sad_views.py",
              ["--output-dir", output_dir]),
        Phase("Phase 4: Export SWE.2 (SAD) to DOCX", "architecture_docx_exporter.py",
              [output_dir, docx_path]),
    ]


def plan_runs(
    cfg: Dict[str, Any],
    *,
    project_path: str,
    selected_group: Optional[str],
    selected_layer: Optional[str] = None,
    selected_components: Optional[List[str]] = None,
    component_per_docx: bool = False,
    use_model: bool,
    no_llm_summarize: bool,
    from_phase: int = 1,
    filter_mode: Optional[str],
    data_dictionary_path: Optional[str] = None,
    data_dictionary_layer: Optional[List[Tuple[str, str]]] = None,
    macros_path: Optional[str] = None,
    macros_layer: Optional[List[Tuple[str, str]]] = None,
    project_name: Optional[str] = None,
    output_name: Optional[str] = None,
    only_files: Optional[str] = None,
    include_emulator: bool = False,
    selected_units: Optional[List[str]] = None,
    doc_type: str = DOC_TYPE_SWE3,
) -> List[RunPlan]:
    """Translate config + CLI flags into a flat list of RunPlan objects.

    Each RunPlan maps to one PhaseRunner.run(...) call. Returning a *list*
    (not a single plan) lets us emit one plan per group while keeping the
    runner itself dead-simple.

    Raises ValueError if selected_group/selected_layer doesn't exist in config.
    """
    p = paths()
    from .config import get_flat_groups
    groups_cfg = get_flat_groups(cfg)
    group_names = sorted(groups_cfg.keys()) if isinstance(groups_cfg, dict) else []

    generate_swe3 = doc_type in (DOC_TYPE_SWE3, DOC_TYPE_BOTH)
    generate_swe2 = doc_type in (DOC_TYPE_SWE2, DOC_TYPE_BOTH)

    resolved_selected = _resolve_group_name(groups_cfg, selected_group)
    if selected_group and not resolved_selected:
        # Allow single-file mode without layer entry
        if selected_group.startswith("_single_file_"):
            resolved_selected = selected_group
        else:
            raise ValueError(
                f"Unknown --selected-group {selected_group!r}. "
                f"Valid groups: {', '.join(group_names) if group_names else '(none)'}"
            )

    # Validate --selected-layer and derive target groups for that layer.
    if selected_layer:
        layer_cfg = (cfg.get("layers") or {}).get(selected_layer)
        if layer_cfg is None:
            valid_layers = sorted((cfg.get("layers") or {}).keys())
            raise ValueError(
                f"Unknown --selected-layer {selected_layer!r}. "
                f"Valid layers: {', '.join(valid_layers) if valid_layers else '(none)'}"
            )
        layer_group_names = set((layer_cfg.get("groups") or {}).keys())
        layer_target_groups = [g for g in group_names if g in layer_group_names]
    else:
        layer_target_groups = []

    plans: List[RunPlan] = []

    # ------------------------------------------------------------------
    # Component selection: one or more explicit component names
    # ------------------------------------------------------------------
    if selected_components:
        from .config import get_component_layer_name
        derived_layer = get_component_layer_name(cfg, selected_components[0])
        virtual_name = "_".join(selected_components)

        if not use_model:
            # SWE.2 always needs the full model, so widen the parse scope when
            # it's requested even though --selected-component narrows SWE.3.
            build_phases = _build_model_phases(
                project_path,
                no_llm_summarize=no_llm_summarize,
                data_dictionary_path=data_dictionary_path,
                data_dictionary_layer=data_dictionary_layer,
                macros_path=macros_path,
                macros_layer=macros_layer,
                selected_layer=None if generate_swe2 else derived_layer,
                project_name=project_name,
                only_files=only_files,
                include_emulator=include_emulator,
            )
            if from_phase <= 2:
                label = ("Build model (all layers)" if generate_swe2 else
                          f"Build model (layer of {', '.join(selected_components)})")
                plans.append(RunPlan(
                    label=label,
                    phases=build_phases,
                    runner_from_phase=from_phase,
                ))

        local_from = max(1, from_phase - 2) if from_phase >= PHASE_VIEWS else 1

        if generate_swe3:
            out_key = output_name.replace(" ", "-") if output_name else virtual_name
            comp_out = os.path.join(p.output_dir, out_key)
            comp_sel_args: List[str] = []
            for c in selected_components:
                comp_sel_args += ["--selected-component", c]
            view_phases = _view_export_phases(
                output_dir=comp_out,
                filter_mode=filter_mode,
                extra_view_args=comp_sel_args,
                docx_args=[
                    os.path.join(comp_out, "interface_tables.json"),
                    os.path.join(comp_out, f"software_detailed_design_{out_key}.docx"),
                ] + comp_sel_args,
                selected_units=selected_units,
            )
            plans.append(RunPlan(
                label=f"Components: {', '.join(selected_components)}",
                phases=view_phases,
                runner_from_phase=local_from,
            ))

        if generate_swe2:
            plans.append(RunPlan(
                label="SWE.2 Architecture Design",
                phases=_swe2_doc_phases(),
                runner_from_phase=local_from,
            ))

        return plans

    # ------------------------------------------------------------------
    # No layer: single flat run, all 4 phases (backward compat)
    # ------------------------------------------------------------------
    if not group_names:
        if generate_swe3:
            if use_model:
                # Skip phases 1+2; runner indices 1,2 map to phases 3,4
                phases = _view_export_phases(filter_mode=filter_mode, selected_units=selected_units)
                translated = max(1, from_phase - 2)
                plans.append(RunPlan(label="single run (use-model)",
                                     phases=phases,
                                     runner_from_phase=translated))
            else:
                phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize,
                                             data_dictionary_path=data_dictionary_path,
                                             data_dictionary_layer=data_dictionary_layer,
                                             macros_path=macros_path,
                                             macros_layer=macros_layer,
                                             project_name=project_name, only_files=only_files,
                                             include_emulator=include_emulator) \
                         + _view_export_phases(filter_mode=filter_mode, selected_units=selected_units)
                plans.append(RunPlan(label="single run",
                                     phases=phases,
                                     runner_from_phase=from_phase))

        if generate_swe2:
            if not use_model and not generate_swe3:
                build_phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize,
                                                    data_dictionary_path=data_dictionary_path,
                                                    data_dictionary_layer=data_dictionary_layer,
                                                    macros_path=macros_path,
                                                    macros_layer=macros_layer,
                                                    project_name=project_name, only_files=only_files,
                                                    include_emulator=include_emulator)
                if from_phase <= 2:
                    plans.append(RunPlan(label="Build model (all layers)",
                                         phases=build_phases,
                                         runner_from_phase=from_phase))
            swe2_from = max(1, from_phase - 2) if from_phase >= PHASE_VIEWS else 1
            plans.append(RunPlan(label="SWE.2 Architecture Design",
                                 phases=_swe2_doc_phases(),
                                 runner_from_phase=swe2_from))

        return plans

    # ------------------------------------------------------------------
    # Layers present: build model, then per-group view+export
    # ------------------------------------------------------------------
    if selected_layer:
        target_groups = layer_target_groups
    elif resolved_selected:
        target_groups = [resolved_selected]
    else:
        target_groups = group_names

    if not use_model:
        # SWE.2 always needs the full model, so widen the parse scope when it's
        # requested even though --selected-group/--selected-layer narrowed SWE.3.
        build_selected_group = None if generate_swe2 else resolved_selected
        build_selected_layer = None if generate_swe2 else selected_layer
        # Build-model plan covers phases 1+2 only.
        build_phases = _build_model_phases(project_path, no_llm_summarize=no_llm_summarize,
                                            data_dictionary_path=data_dictionary_path,
                                            data_dictionary_layer=data_dictionary_layer,
                                            macros_path=macros_path,
                                            macros_layer=macros_layer,
                                            selected_group=build_selected_group,
                                            selected_layer=build_selected_layer,
                                            project_name=project_name, only_files=only_files,
                                            include_emulator=include_emulator)
        # If the user wants to start at phase >= 3, the build step is skipped
        # entirely (use existing model on disk).
        if from_phase <= 2:
            if build_selected_group:
                label = f"Build model (layer of {build_selected_group})"
            elif build_selected_layer:
                label = f"Build model ({build_selected_layer})"
            else:
                label = "Build model (all layers)"
            plans.append(RunPlan(label=label,
                                 phases=build_phases,
                                 runner_from_phase=from_phase))

    local_from = max(1, from_phase - 2) if from_phase >= PHASE_VIEWS else 1
    for g in (target_groups if generate_swe3 else []):
        # Single-file mode: use allowed components from config, not from layer
        is_single_file = g.startswith("_single_file_")
        if is_single_file:
            # For single-file mode, get allowed components from config and skip layer lookup
            allowed_components = (cfg.get("_analyzerAllowedComponents") or [])
            if not allowed_components:
                raise ValueError(
                    f"Single-file mode requires _analyzerAllowedComponents in config"
                )
            # Create phases with defaults - views will use _analyzerAllowedComponents directly
            # We need to make _analyzerAllowedComponents available to the subprocess via a new flag
            view_phases = _view_export_phases(
                selected_group=g,
                filter_mode=filter_mode,
                selected_units=selected_units,
            )
            # Embed allowed components into the phase args to pass via CLI
            for phase in view_phases:
                allowed_components_quoted = ",".join(allowed_components)
                phase.args.extend(["--allowed-components", allowed_components_quoted])
        elif component_per_docx:
            grp = groups_cfg.get(g, {})
            if not isinstance(grp, dict):
                continue
            for comp_name in grp.keys():
                comp = comp_name.replace(" ", "-")
                comp_out = os.path.join(p.output_dir, comp)
                comp_sel_args = ["--selected-component", comp]
                view_phases = _view_export_phases(
                    output_dir=comp_out,
                    filter_mode=filter_mode,
                    extra_view_args=comp_sel_args,
                    docx_args=[
                        os.path.join(comp_out, "interface_tables.json"),
                        os.path.join(comp_out, f"software_detailed_design_{comp}.docx"),
                    ] + comp_sel_args,
                selected_units=selected_units,
                )
                plans.append(RunPlan(label=f"Component: {comp}",
                                     phases=view_phases,
                                     runner_from_phase=local_from))
        else:
            g_safe = g.replace(" ", "-")
            out_key = output_name.replace(" ", "-") if output_name else g_safe
            group_out = os.path.join(p.output_dir, out_key)
            view_phases = _view_export_phases(
                output_dir=group_out,
                selected_group=g,
                filter_mode=filter_mode,
                docx_args=[
                    os.path.join(group_out, "interface_tables.json"),
                    os.path.join(group_out, f"software_detailed_design_{out_key}.docx"),
                    "--selected-group", g,
                ],
                selected_units=selected_units,
            )
            plans.append(RunPlan(label=f"Group: {g}",
                                 phases=view_phases,
                                 runner_from_phase=local_from))

    if generate_swe2:
        plans.append(RunPlan(label="SWE.2 Architecture Design",
                             phases=_swe2_doc_phases(),
                             runner_from_phase=local_from))

    return plans
