#!/usr/bin/env python3
"""Sequence diagram generator for behavior diagram generation."""

import os
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from .tracer import CallChainTracer
from .mermaid_builder import MermaidBuilder
from .llm_call_description import CallDescriptionGenerator
from .selector import create_diagram_selector
from .utils import load_json, safe_filename


class SequenceDiagramGenerator:
    """Generates Mermaid sequence diagrams from function call data."""

    # Default component name when component cannot be determined
    UNKNOWN_COMPONENT = "Unknown"

    # Track the current/target component for color assignment
    current_component = None

    def __init__(self, components_file: str, units_file: str, functions_file: str,
                 config: Optional[Dict] = None):
        """
        Initialize the generator with JSON data files.

        Args:
            components_file: Path to components.json
            units_file: Path to units.json
            functions_file: Path to functions.json
            config: Optional configuration dictionary for diagram generation
                If not provided, uses default settings (single_per_external_component)
        """
        self.components_file = components_file
        self.units_file = units_file
        self.functions_file = functions_file
        self.config = config or {}

        self.components_data = self._safe_load(components_file)
        self.units_data = self._safe_load(units_file)
        self.functions_data = self._safe_load(functions_file)

        # Build lookup maps: function -> unit, unit -> component.
        self.function_to_unit: Dict[str, str] = {}
        self.unit_to_component: Dict[str, str] = {}
        for unit_key, unit in (self.units_data or {}).items():
            if not isinstance(unit, dict):
                continue
            self.unit_to_component[unit_key] = unit_key.split("|")[0] if "|" in unit_key else unit_key
            for fid in unit.get("functionIds", []) or []:
                self.function_to_unit[fid] = unit_key

        self.tracer = CallChainTracer(
            self.function_to_unit, self.unit_to_component,
            self.functions_data, self.UNKNOWN_COMPONENT,
        )
        self.describer = CallDescriptionGenerator(self.config)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_load(path: str) -> Dict:
        """Load a JSON file, returning {} on any error (missing/invalid)."""
        try:
            if path and os.path.isfile(path):
                return load_json(path)
        except SystemExit:
            # load_json exits on error; treat as empty for library use.
            pass
        except Exception:
            pass
        return {}

    def _component_for_function(self, func: str) -> str:
        unit = self.function_to_unit.get(func)
        if unit:
            return self.unit_to_component.get(unit, self.UNKNOWN_COMPONENT)
        parts = (func or "").split("|")
        return parts[0] if parts and parts[0] else self.UNKNOWN_COMPONENT

    def _unit_for_function(self, func: str) -> str:
        unit = self.function_to_unit.get(func)
        if unit:
            return unit
        parts = (func or "").split("|")
        return "|".join(parts[:2]) if len(parts) >= 2 else (func or "")

    def get_function_name(self, func_key: str) -> str:
        """Display name for a function key (qualifiedName, leaf of ::)."""
        fn = self.functions_data.get(func_key, {}) or {}
        qualified = fn.get("qualifiedName") or ""
        if not qualified:
            parts = (func_key or "").split("|")
            qualified = parts[2] if len(parts) >= 3 else (func_key or "")
        return qualified.split("::")[-1] if "::" in qualified else qualified

    def _unit_name(self, unit_key: str) -> str:
        unit = self.units_data.get(unit_key, {}) or {}
        name = unit.get("name")
        if name:
            return name
        return unit_key.split("|")[-1] if "|" in unit_key else unit_key

    # ------------------------------------------------------------------
    # Diagram construction
    # ------------------------------------------------------------------
    def _build_diagram(self, function_key: str, caller_key: str) -> str:
        """Build the Mermaid source for one (current, external caller) diagram."""
        builder = MermaidBuilder(self._component_for_function(function_key))

        current_unit = self._unit_for_function(function_key)
        caller_unit = self._unit_for_function(caller_key)

        participants: List[Tuple[str, str]] = [
            (builder.participant_id(caller_unit), self._unit_name(caller_unit)),
            (builder.participant_id(current_unit), self._unit_name(current_unit)),
        ]
        messages: List[Tuple[str, str, str]] = [
            (
                builder.participant_id(caller_unit),
                builder.participant_id(current_unit),
                f"{self.get_function_name(function_key)}()",
            )
        ]

        # Forward calls out of the current function (one hop).
        fn = self.functions_data.get(function_key, {}) or {}
        for callee in fn.get("callsIds", []) or []:
            if not callee:
                continue
            callee_unit = self._unit_for_function(callee)
            participants.append((builder.participant_id(callee_unit), self._unit_name(callee_unit)))
            messages.append((
                builder.participant_id(current_unit),
                builder.participant_id(callee_unit),
                f"{self.get_function_name(callee)}()",
            ))

        title = f"{self._unit_name(caller_unit)} -> {self.get_function_name(function_key)}"
        return builder.build_sequence_diagram(participants, messages, title=title)

    def generate_all_diagrams(self, function_key: str,
                              output_dir: str) -> Tuple[List[str], List[str]]:
        """
        Create one .mmd per external caller of function_key.

        Returns a tuple (mmd_paths, descriptions) where the two lists are
        parallel and ordered to match the external callers in calledByIds.
        Returns ([], []) when there are no external callers.
        """
        if not function_key:
            return [], []

        os.makedirs(output_dir, exist_ok=True)

        mode = self.config.get("_behaviourSelector") if isinstance(self.config, dict) else None
        selector = create_diagram_selector(
            mode, self.function_to_unit, self.unit_to_component,
            self.functions_data, self.UNKNOWN_COMPONENT,
        )
        external_callers = selector.select_external_callers(function_key)

        mmd_paths: List[str] = []
        descriptions: List[str] = []

        for caller_key in external_callers:
            safe_c = safe_filename((function_key or "").replace("|", "_"))
            safe_k = safe_filename((caller_key or "").replace("|", "_"))
            mmd_path = os.path.join(output_dir, f"{safe_c}__{safe_k}.mmd")
            try:
                with open(mmd_path, "w", encoding="utf-8") as f:
                    f.write(self._build_diagram(function_key, caller_key))
            except OSError:
                break
            mmd_paths.append(mmd_path)
            descriptions.append(
                self.describer.get_call_description(
                    caller_key, function_key, self.get_function_name, self.functions_data,
                )
            )

        return mmd_paths, descriptions

    def list_functions(self) -> List[str]:
        """Return all known function keys."""
        return list(self.functions_data.keys())
