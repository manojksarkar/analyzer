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

    def __init__(self, components_file, units_file, functions_file,
                 config: Optional[Dict] = None):
        """
        Initialize the generator with model data (or, historically, paths to it).

        Each of the three accepts EITHER an already-loaded dict or a path to the JSON file
        (doc 10, step 5). The caller normally has the data already — run_views loads the model
        through `core.model_io` before invoking any view — and in database mode the files do not
        exist, so a path is no longer something a caller can always produce.

        Args:
            components_file: components data, or a path to components.json
            units_file: units data, or a path to units.json
            functions_file: functions data, or a path to functions.json
            config: Optional configuration dictionary for diagram generation
                    If not provided, uses default settings (single_per_external_component)
        """
        self.components = self._safe_load(components_file)
        self.units = self._safe_load(units_file)
        self.functions = self._safe_load(functions_file)

        # Build reverse lookup: function -> unit
        self.function_to_unit = self._build_function_to_unit_map()

        # Build reverse lookup: unit -> component
        self.unit_to_component = self._build_unit_to_component_map()

        # Get the filter mode from config, default to "single_per_external_component"
        self.filter_mode = self._get_filter_mode(config)

        # Store config for LLM calls
        self.config = config

        # Initialize components
        self._tracer = CallChainTracer(
            self.function_to_unit,
            self.unit_to_component,
            self.functions,
            self.UNKNOWN_COMPONENT
        )
        self._mermaid_builder = MermaidBuilder(current_component=None)
        self._call_description = CallDescriptionGenerator(config)

        # Current component will be set dynamically based on the function being analyzed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_load(path) -> Dict:
        """Model data, from a dict passed straight through or a JSON file path.

        Accepting a dict is what lets the caller hand over the model it already loaded through
        `core.model_io` (doc 10, step 5) — in database mode there is no file to point at. Still
        returns {} on any error, so a missing artifact degrades exactly as before.
        """
        if isinstance(path, dict):
            return path
        try:
            if path and os.path.isfile(path):
                return load_json(path)
        except SystemExit:
            # load_json exits on error; treat as empty for library use.
            pass
        except Exception:
            pass
        return {}

    def _get_filter_mode(self, config: Optional[Dict]) -> str:
        """
        Get the filter mode from configuration.

        Args:
            config: Optional configuration dictionary

        Returns:
            The filter mode string (default: "skip_within_unit")
        """

        if config is None:
            return "skip_within_unit"

        # Try to get from views.sequenceDiagrams.filterMode
        views_config = config.get("views", {})
        sequence_config = views_config.get("sequenceDiagrams", {})
        filter_mode = sequence_config.get("filterMode", "skip_within_unit")

        return filter_mode

    def _build_function_to_unit_map(self) -> Dict[str, str]:
        """Build a mapping from function name to unit name."""
        mapping = {}
        for unit_name, unit_data in self.units.items():
            for func_name in unit_data.get("functionIds", []):
                mapping[func_name] = unit_name
        return mapping

    def _build_unit_to_component_map(self) -> Dict[str, str]:
        """Build a mapping from unit name to component name."""
        mapping = {}
        for component_name, component_data in self.components.items():
            for unit_name in component_data.get("units", []):
                mapping[unit_name] = component_name
        return mapping

    def get_component_color(self, component_name: str) -> str:
        """Get color for a component.
        Returns skyblue for current component, lightgreen for external components."""
        if self.current_component and component_name == self.current_component:
            return MermaidBuilder.CURRENT_COMPONENT_COLOR
        else:
            return MermaidBuilder.EXTERNAL_COMPONENT_COLOR

    # Backward compatibility: expose internal methods that were moved to other classes
    def _get_external_caller_component(self, backward_calls: List[Tuple[str, str]],
                                       start_function: str) -> Optional[str]:
        """Get the component of the first external caller (backward compatibility)."""
        return self._mermaid_builder.get_external_caller_component(
            backward_calls, start_function, self.function_to_unit, self.unit_to_component
        )

    def _build_unit_order(self, backward_calls: List[Tuple[str, str]],
                          forward_calls: List[Tuple[str, str]]) -> Dict[str, int]:
        """Build ordering map for units (backward compatibility)."""
        return self._tracer.build_unit_order(backward_calls, forward_calls)

    def _build_call_context(self, callerFn: str, calleeFn: str) -> str:
        """Build context string from function descriptions (backward compatibility)."""
        return self._call_description.build_call_context(
            callerFn, calleeFn, self.get_function_name, self.functions
        )
        """Get color for a component.
        Returns skyblue for current component, lightgreen for external components."""
        if self.current_component and component_name == self.current_component:
            return MermaidBuilder.CURRENT_COMPONENT_COLOR
        else:
            return MermaidBuilder.EXTERNAL_COMPONENT_COLOR

    def get_function_name(self, function_key: str) -> str:
        """Get the actual function name from function key using qualifiedName."""
        func_data = self.functions.get(function_key)
        if func_data:
            return func_data.get("qualifiedName", function_key)
        return function_key

    def list_all_functions(self) -> List[str]:
        """List all available functions."""
        return list(self.functions.keys())

    def get_external_callers(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Get all external callers for a target function.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) for each external caller
        """
        return self._tracer.get_external_callers(target_function)

    def trace_call_chain(self, start_function: str) -> List[Tuple[str, str]]:
        """
        Trace the complete call chain starting from a function.
        Traces backward through called_by to find external callers,
        then forward through calls to find all internal calls.

        Args:
            start_function: Name of the function to start tracing from

        Returns:
            List of tuples (caller_function, callee_function) representing the call chain
        """
        return self._tracer.trace_call_chain(start_function)

    def get_participants(self, call_chain: List[Tuple[str, str]]) -> Dict[str, Dict]:
        """
        Get all participants (units) involved in the call chain.

        Returns:
            Dictionary mapping unit_id to unit info
        """
        return self._tracer.get_participants(call_chain)

    def get_call_description(self, callerFn: str, calleeFn: str) -> str:
        """
        Get the description for a function call.

        Args:
            callerFn: The function that calls the callee
            calleeFn: The function that is being called
        Returns:
            A description of why a function is being called
        """
        return self._call_description.get_call_description(
            callerFn,
            calleeFn,
            self.get_function_name,
            self.functions
        )

    def generate_diagram(self, start_function: str) -> Tuple[str, List[str]]:
        """
        Generate a Mermaid sequence diagram for the given function.

        Args:
            start_function: Name of the function to generate diagram for

        Returns:
            Tuple of (Mermaid sequence diagram string, list of behavior descriptions)
        """
        call_chain = self._tracer.trace_call_chain(start_function)

        if not call_chain:
            return f"sequenceDiagram\n    Note over Start: No call chain found for function '{start_function}'", []

        # Separate backward calls (external callers) from forward calls (internal)
        backward_calls = [(c, e) for c, e in call_chain if e == start_function]
        forward_calls = [(c, e) for c, e in call_chain if e != start_function]

        # Get all participants and group by component
        participants = self._tracer.get_participants(call_chain)
        component_participants = defaultdict(list)
        for unit_id, info in participants.items():
            component_participants[info["component"]].append((unit_id, info))

        # Determine component ordering (external caller's component first)
        external_caller_component = self._mermaid_builder.get_external_caller_component(
            backward_calls, start_function, self.function_to_unit, self.unit_to_component
        )

        # Determine unit ordering based on call chain appearance
        unit_order = self._tracer.build_unit_order(backward_calls, forward_calls)

        # Build diagram
        diagram_lines = self._mermaid_builder.build_diagram_lines(
            component_participants, external_caller_component, unit_order
        )

        # Build call tree for forward calls
        call_tree = defaultdict(list)
        for caller, callee in forward_calls:
            call_tree[caller].append(callee)

        # Add call arrows and behavior descriptions
        behavior_descriptions = []
        self._mermaid_builder.add_backward_calls(
            diagram_lines, backward_calls, behavior_descriptions,
            self.function_to_unit, self.get_function_name
        )
        self._mermaid_builder.add_forward_calls_recursive(
            start_function, call_tree, diagram_lines, behavior_descriptions,
            self.function_to_unit, self.get_function_name, self.get_call_description
        )
        self._mermaid_builder.add_backward_returns(
            diagram_lines, backward_calls, behavior_descriptions,
            self.function_to_unit, self.get_function_name
        )

        return "\n".join(diagram_lines), behavior_descriptions

    def generate_diagram_for_caller(self, target_function: str, caller_function: str,
                                    skip_within_unit: bool = False) -> Tuple[str, List[str], bool]:
        """
        Generate a Mermaid sequence diagram for a specific external caller to the target function.

        The diagram only shows interactions within the target function's component (the component in focus).
        Calls to all external components (including the caller's component) are ignored.

        Args:
            target_function: Name of the target function
            caller_function: Name of the external caller function
            skip_within_unit: If True, skip all calls within the same unit (calls where
                caller and callee belong to the same unit)

        Returns:
            Tuple of (Mermaid sequence diagram string, behaviour descriptions,
            has_internal_call). ``has_internal_call`` is True when the diagram
            contains at least one forward (cross-unit) arrow —
            i.e. the traced call chain is non-empty.
        """
        # Get the components involved
        caller_unit = self.function_to_unit.get(caller_function)
        caller_component = self.unit_to_component.get(caller_unit, self.UNKNOWN_COMPONENT) if caller_unit else self.UNKNOWN_COMPONENT

        target_unit = self.function_to_unit.get(target_function)
        target_component = self.unit_to_component.get(target_unit, self.UNKNOWN_COMPONENT) if target_unit else self.UNKNOWN_COMPONENT

        # Set the current component to the target component for coloring
        self.current_component = target_component
        self._mermaid_builder.current_component = target_component

        # Trace forward from the target function to get all internal calls
        call_chain = self._tracer.trace_forward_within_component(
            target_function, target_component, skip_within_unit
        )

        # Get all participants (caller + all units in the call chain)
        participants = {}
        functions_in_chain = {caller_function, target_function}

        for caller, callee in call_chain:
            functions_in_chain.add(caller)
            functions_in_chain.add(callee)

        # When skip_within_unit is enabled, the tracer now bridges skipped
        # intra-unit hops so every emitted edge chains from target_function
        # (see tracer.trace_forward_within_component). This reachability filter
        # is therefore redundant, but kept as a harmless safety net: with
        # bridging no function is orphaned, so it prunes nothing.
        if skip_within_unit:
            # Build a set starting from caller/target, then add callees whose parents are in the set
            reachable_functions = {caller_function, target_function}
            changed = True
            while changed:
                changed = False
                for caller, callee in call_chain:
                    if caller in reachable_functions and callee not in reachable_functions:
                        reachable_functions.add(callee)
                        changed = True
            functions_in_chain = reachable_functions

        # Map functions to units
        for func in functions_in_chain:
            unit = self.function_to_unit.get(func)
            if unit:
                component = self.unit_to_component.get(unit, self.UNKNOWN_COMPONENT)
                unit_id = unit.replace("|", "/")

                if unit_id not in participants:
                    participants[unit_id] = {
                        "unit": unit,
                        "component": component,
                        "functions": []
                    }
                participants[unit_id]["functions"].append(func)

        # Group participants by component
        component_participants = defaultdict(list)
        for unit_id, info in participants.items():
            component_participants[info["component"]].append((unit_id, info))

        # Build diagram
        diagram_lines, behavior_descriptions = self._mermaid_builder.build_diagram_for_caller(
            component_participants, caller_component, call_chain, target_function,
            caller_function, self.function_to_unit, self.get_function_name, self.get_call_description
        )

        # Reset current component after generation
        self.current_component = None
        self._mermaid_builder.current_component = None

        # An internal (forward, cross-unit within-component) arrow exists iff the
        # traced call chain is non-empty.
        has_internal_call = bool(call_chain)

        return "\n".join(diagram_lines), behavior_descriptions, has_internal_call

    def generate_all_diagrams(self, target_function: str, output_dir: str = ".") -> Tuple[List[str], List[List[str]]]:
        """
        Generate separate sequence diagrams for each external caller to the target function.

        Uses the configured filter mode to determine which diagrams should be generated:
        - "single_per_function": One diagram per target function (default)
        - "single_per_external_component": One diagram per external component
        - "all_callers": One diagram for every external caller function
        - "multi_unit_functions": Maximum diagrams per function (one per unique external
          caller), but only for functions involving more than one unit
        - "skip_within_unit": One diagram per function (only if 2+ units), skips
          internal calls within the same unit

        Args:
            target_function: Name of the target function
            output_dir: Directory to save diagrams (default: current directory)

        Returns:
            List of generated file paths
        """
        # Create the appropriate selector based on filter_mode configuration
        selector = create_diagram_selector(
            self.filter_mode,
            self.function_to_unit,
            self.unit_to_component,
            self.functions,
            self.UNKNOWN_COMPONENT
        )

        # Use the selector to get the list of callers to generate diagrams for
        selected_callers = selector.select_diagrams_to_generate(target_function)

        if not selected_callers:
            return [], []

        # Determine if we should skip within-unit calls based on filter mode
        skip_within_unit = (self.filter_mode == "skip_within_unit")

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        generated_files = []
        descriptions = []
        for caller_function, caller_component in selected_callers:
            # Generate diagram for this caller
            diagram, behaviour_descriptions, has_internal_call = self.generate_diagram_for_caller(
                target_function, caller_function, skip_within_unit=skip_within_unit
            )

            # Guard: skip diagrams with no internal (same-component cross-unit)
            # arrow. This enforces the invariant that every emitted behaviour
            # diagram shows at least one cross-unit call within the component,
            # rather than an empty "external -> target -> Return" diagram.
            if skip_within_unit and not has_internal_call:
                continue

            descriptions.append(behaviour_descriptions)
            # Create filename: target_function__caller_function.mmd
            safe_caller = safe_filename(caller_function)
            safe_target = safe_filename(target_function)
            filename = f"{safe_target}__{safe_caller}.mmd"
            filepath = os.path.join(output_dir, filename)

            # Write to file
            with open(filepath, 'w') as f:
                f.write(diagram)

            generated_files.append(filepath)

        return generated_files, descriptions

    def get_selection_summary(self, target_function: str) -> Dict:
        """
        Get a summary of which diagrams would be generated for a target function.

        This uses the configured filter mode to analyze and return details about
        the diagram selection process.

        Args:
            target_function: Name of the target function

        Returns:
            Dictionary with selection details including:
            - target_function: The target function name
            - filter_mode: The current filter mode
            - external_components: List of external components that call the target
            - callers_per_component: Count of callers per component
            - selected_diagrams: List of selected (caller, component) pairs
            - total_diagrams_to_generate: Number of diagrams to generate

        Filter modes:
        - "single_per_function": One diagram per target function
        - "single_per_external_component": One diagram per external component
        - "all_callers": One diagram per unique external caller function
        - "multi_unit_functions": Maximum diagrams per function (one per unique
          external caller), but only for functions involving more than one unit
        """
        # Create the appropriate selector based on filter_mode configuration
        selector = create_diagram_selector(
            self.filter_mode,
            self.function_to_unit,
            self.unit_to_component,
            self.functions,
            self.UNKNOWN_COMPONENT
        )

        summary = selector.get_selection_summary(target_function)
        summary["filter_mode"] = self.filter_mode
        return summary
