#!/usr/bin/env python3
"""Diagram selector classes for behavior diagram generation."""

from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict


class DiagramSelectorBase:
    """
    Base class for diagram selection strategies.

    This class defines the interface for selecting which sequence diagrams
    should be generated based on external component callers.
    """

    def __init__(self, function_to_unit_map: Dict[str, str], unit_to_component_map: Dict[str, str],
                 functions_data: Dict, unknown_component: str = "Unknown"):
        """
        Initialize the DiagramSelector.

        Args:
            function_to_unit_map: Mapping from function name to unit name
            unit_to_component_map: Mapping from unit name to component name
            functions_data: The functions data dictionary
            unknown_component: Default component name when component cannot be determined
        """
        self.function_to_unit = function_to_unit_map
        self.unit_to_component = unit_to_component_map
        self.functions = functions_data
        self.UNKNOWN_COMPONENT = unknown_component

    def _get_component_for_function(self, func: str) -> str:
        """Get the component name for a given function."""
        unit = self.function_to_unit.get(func)
        if unit:
            return self.unit_to_component.get(unit, self.UNKNOWN_COMPONENT)
        return self.UNKNOWN_COMPONENT

    def get_external_callers_with_component(self, target_function: str) -> Dict[str, List[Tuple[str, str]]]:
        """
        Get all external callers for a target function, grouped by their component.

        Args:
            target_function: Name of the target function

        Returns:
            Dictionary mapping component_name to list of (caller_function, caller_component) tuples
        """
        external_callers_by_component = defaultdict(list)
        visited = set()

        def trace_callers(current_func: str):
            if current_func in visited:
                return
            visited.add(current_func)

            current_unit = self.function_to_unit.get(current_func)
            current_component = self.unit_to_component.get(current_unit, self.UNKNOWN_COMPONENT)

            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for caller in func_data.get("calledByIds", []):
                caller_unit = self.function_to_unit.get(caller)
                if caller_unit:
                    caller_component = self.unit_to_component.get(caller_unit, self.UNKNOWN_COMPONENT)
                    if caller_component != current_component:
                        external_callers_by_component[caller_component].append((caller, caller_component))
                    trace_callers(caller)

        trace_callers(target_function)
        return dict(external_callers_by_component)

    def select_diagrams_to_generate(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Select which diagrams should be generated based on the selection logic.

        Selection Logic:
        1. Generate at least one diagram for calls from all external components interacting with it
        2. Do not generate the diagram for same function call from different external components.
           Create only if the external component doesn't have any other calls.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) to generate diagrams for
        """
        # Get all external callers grouped by component
        external_callers_by_component = self.get_external_callers_with_component(target_function)

        selected_callers = []

        for component_name, callers in external_callers_by_component.items():
            # For each external component, select at least one caller
            # If the component has only one caller, use that one
            # If the component has multiple callers, use the first one (they all call the same target)
            if callers:
                # Select the first caller from each component
                # This ensures we have at least one diagram per external component
                selected_callers.append(callers[0])

        return selected_callers

    def get_selection_summary(self, target_function: str) -> Dict:
        """
        Get a summary of the diagram selection process for debugging/analysis.

        Args:
            target_function: Name of the target function

        Returns:
            Dictionary with selection details
        """
        external_callers_by_component = self.get_external_callers_with_component(target_function)
        selected = self.select_diagrams_to_generate(target_function)

        return {
            "target_function": target_function,
            "external_components": list(external_callers_by_component.keys()),
            "callers_per_component": {mod: len(callers) for mod, callers in external_callers_by_component.items()},
            "selected_diagrams": [{"caller": c[0], "component": c[1]} for c in selected],
            "total_diagrams_to_generate": len(selected)
        }


class SingleExternalModuleDiagramSelector(DiagramSelectorBase):
    """
    Diagram selector that generates exactly one diagram per external component.

    Selection Logic:
    - For each external component that calls the target function, generate exactly one diagram
    - The diagram represents how any function from that external component calls the target
    - This is useful when you want a simplified view with one diagram per external component

    This is the "single_per_external_component" filter mode.
    """

    def select_diagrams_to_generate(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Select which diagrams should be generated.

        This implementation generates exactly one diagram per external component,
        regardless of how many functions from that component call the target.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) - one per external component
        """
        # Get all external callers grouped by component
        external_callers_by_component = self.get_external_callers_with_component(target_function)

        selected_callers = []

        for component_name, callers in external_callers_by_component.items():
            # For each external component, select exactly one caller
            # This ensures we have exactly one diagram per external component
            if callers:
                # Select the first caller from each component
                selected_callers.append(callers[0])

        return selected_callers


class AllExternalCallersDiagramSelector(DiagramSelectorBase):
    """
    Diagram selector that generates a diagram for every unique external caller function.

    Selection Logic:
    - Generate a separate diagram for each unique external caller function
    - Each caller function is only included once, even if called from multiple paths
    - This provides detailed coverage without duplicate diagrams for the same caller

    This is the "all_callers" filter mode.
    """

    def select_diagrams_to_generate(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Select which diagrams should be generated.

        This implementation generates a diagram for every unique external caller function.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) - one per unique caller function
        """
        # Get all external callers grouped by component
        external_callers_by_component = self.get_external_callers_with_component(target_function)

        # Collect unique callers - one per function (not per component)
        # Use a dict to track unique caller functions
        unique_callers = {}

        for component_name, callers in external_callers_by_component.items():
            for caller_function, caller_component in callers:
                # Only add if we haven't seen this caller function before
                if caller_function not in unique_callers:
                    unique_callers[caller_function] = (caller_function, caller_component)

        # Return unique callers as a list
        return list(unique_callers.values())


class SingleFunctionDiagramSelector(DiagramSelectorBase):
    """
    Diagram selector that generates exactly one diagram per target function.

    Selection Logic:
    - Generate only ONE diagram for the target function
    - Select the first available external caller (if any) to represent the call
    - If no external callers exist, generate a self-contained diagram for the function
    - This is the simplest filter mode - one diagram per function

    This is the "single_per_function" filter mode.
    """

    def select_diagrams_to_generate(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Select which diagrams should be generated.

        This implementation generates exactly one diagram per target function,
        regardless of how many external callers or components call it.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) - exactly one entry
        """
        # Get all external callers grouped by component
        external_callers_by_component = self.get_external_callers_with_component(target_function)

        # Collect all callers from all components
        all_callers = []
        for component_name, callers in external_callers_by_component.items():
            all_callers.extend(callers)

        # Return only the first caller (or empty list if no external callers)
        # This ensures we generate exactly one diagram per function
        if all_callers:
            return [all_callers[0]]
        else:
            return []


class SkipWithinUnitDiagramSelector(DiagramSelectorBase):
    """
    Diagram selector that skips calls within the same unit.

    Selection Logic:
    - Generate only ONE diagram per target function (like single_per_function)
    - Only generate diagram if the function involves at least 2 internal units
      (like multi_unit_functions)
    - Skip all calls within the same unit between a call from a different component/unit
      and a call to another unit

    This is the "skip_within_unit" filter mode.

    Example call flow:
      ExternalCaller (ModuleA) → FuncInModuleB (Unit2) → InternalFunc (Unit2) → FuncInModuleC (Unit3)

    Without filtering: Shows all calls
    With skip_within_unit: Skips the InternalFunc call since it's within Unit2
    """

    def select_diagrams_to_generate(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Select which diagrams should be generated.

        This implementation:
        1. Generates exactly one diagram per target function
        2. Only generates if the function involves more than one unit
        3. The diagram generation will skip internal unit calls

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) - exactly one entry
        """
        # First, check if the target function involves more than one unit
        # by tracing the call chain and counting unique units
        units_in_forward_chain = self._get_units_in_forward_call_chain(target_function)

        # Only generate diagrams if more than one unit is involved
        if len(units_in_forward_chain) <= 1:
            return []

        # Get all external callers grouped by component
        external_callers_by_component = self.get_external_callers_with_component(target_function)

        # Collect all callers from all components
        all_callers = []
        for component_name, callers in external_callers_by_component.items():
            all_callers.extend(callers)

        # Return only the first caller (or empty list if no external callers)
        # This ensures we generate exactly one diagram per function
        if all_callers:
            return [all_callers[0]]
        else:
            return []

    def _get_units_in_forward_call_chain(self, target_function: str) -> Set[str]:
        """
        Get all unique units involved in the call chain of a function.

        This traces both backward (callers) and forward (callees) to find
        all units that are part of the function's execution.

        Args:
            target_function: Name of the target function

        Returns:
            Set of unit names involved in the call chain
        """
        units = set()
        visited = set()
        target_component = self._get_component_for_function(target_function)
        # Trace forward to find all callee units
        def trace_forward(current_func: str):
            if current_func in visited:
                return
            visited.add(current_func)

            current_unit = self.function_to_unit.get(current_func)
            current_component = self._get_component_for_function(current_func)
            if current_unit and current_component == target_component:
                units.add(current_unit)
            else:
                return

            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for callee in func_data.get("callsIds", []):
                trace_forward(callee)

        trace_forward(target_function)

        return units

    def get_selection_summary(self, target_function: str) -> Dict:
        """
        Get a summary of the diagram selection process for debugging/analysis.

        Args:
            target_function: Name of the target function

        Returns:
            Dictionary with selection details including unit count check
        """
        units_in_chain = self._get_units_in_forward_call_chain(target_function)
        external_callers_by_component = self.get_external_callers_with_component(target_function)
        selected = self.select_diagrams_to_generate(target_function)

        return {
            "target_function": target_function,
            "filter_mode": "skip_within_unit",
            "units_in_call_chain": list(units_in_chain),
            "unit_count": len(units_in_chain),
            "involves_multiple_units": len(units_in_chain) > 1,
            "external_components": list(external_callers_by_component.keys()),
            "callers_per_component": {mod: len(callers) for mod, callers in external_callers_by_component.items()},
            "selected_diagrams": [{"caller": c[0], "component": c[1]} for c in selected],
            "total_diagrams_to_generate": len(selected)
        }


class MultiUnitFunctionDiagramSelector(DiagramSelectorBase):
    """
    Diagram selector that generates diagrams only for functions involving more than one unit.

    Selection Logic:
    - Generate a diagram for each unique external caller function
    - BUT only if the target function involves more than one unit in its call chain
    - This filters out functions that are self-contained (only involve their own unit)
    - "Maximum diagram per function" - one diagram per unique external caller

    This is the "multi_unit_functions" filter mode.
    """

    def select_diagrams_to_generate(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Select which diagrams should be generated.

        This implementation generates a diagram for every unique external caller function,
        BUT only if the target function's call chain involves more than one unit.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) - one per unique caller function
            that calls a function involving more than one unit
        """
        # First, check if the target function involves more than one unit
        # by tracing the call chain and counting unique units
        units_in_chain = self._get_units_in_call_chain(target_function)

        # Only generate diagrams if more than one unit is involved
        if len(units_in_chain) <= 1:
            return []

        # Get all external callers grouped by component
        external_callers_by_component = self.get_external_callers_with_component(target_function)

        # Collect unique callers - one per function (not per component)
        unique_callers = {}

        for component_name, callers in external_callers_by_component.items():
            for caller_function, caller_component in callers:
                # Only add if we haven't seen this caller function before
                if caller_function not in unique_callers:
                    unique_callers[caller_function] = (caller_function, caller_component)

        # Return unique callers as a list
        return list(unique_callers.values())

    def _get_units_in_call_chain(self, target_function: str) -> Set[str]:
        """
        Get all unique units involved in the call chain of a function.

        This traces both backward (callers) and forward (callees) to find
        all units that are part of the function's execution.

        Args:
            target_function: Name of the target function

        Returns:
            Set of unit names involved in the call chain
        """
        units = set()
        visited = set()

        # Trace backward to find all caller units
        def trace_backward(current_func: str):
            if current_func in visited:
                return
            visited.add(current_func)

            current_unit = self.function_to_unit.get(current_func)
            if current_unit:
                units.add(current_unit)

            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for caller in func_data.get("calledByIds", []):
                trace_backward(caller)

        # Trace forward to find all callee units
        def trace_forward(current_func: str):
            if current_func in visited:
                return
            visited.add(current_func)

            current_unit = self.function_to_unit.get(current_func)
            if current_unit:
                units.add(current_unit)

            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for callee in func_data.get("callsIds", []):
                trace_forward(callee)

        # Trace both directions
        trace_backward(target_function)
        trace_forward(target_function)

        return units

    def get_selection_summary(self, target_function: str) -> Dict:
        """
        Get a summary of the diagram selection process for debugging/analysis.

        Args:
            target_function: Name of the target function

        Returns:
            Dictionary with selection details including unit count check
        """
        units_in_chain = self._get_units_in_call_chain(target_function)
        external_callers_by_component = self.get_external_callers_with_component(target_function)
        selected = self.select_diagrams_to_generate(target_function)

        return {
            "target_function": target_function,
            "filter_mode": "multi_unit_functions",
            "units_in_call_chain": list(units_in_chain),
            "unit_count": len(units_in_chain),
            "involves_multiple_units": len(units_in_chain) > 1,
            "external_components": list(external_callers_by_component.keys()),
            "callers_per_component": {mod: len(callers) for mod, callers in external_callers_by_component.items()},
            "selected_diagrams": [{"caller": c[0], "component": c[1]} for c in selected],
            "total_diagrams_to_generate": len(selected)
        }


# Backward compatibility alias
DiagramSelector = SingleExternalModuleDiagramSelector


def create_diagram_selector(filter_mode: str, function_to_unit_map: Dict[str, str],
                            unit_to_component_map: Dict[str, str], functions_data: Dict,
                            unknown_component: str = "Unknown") -> DiagramSelectorBase:
    """
    Factory function to create the appropriate diagram selector based on filter mode.

    Args:
        filter_mode: The filtering mode string:
            - "single_per_function": One diagram per target function
            - "single_per_external_component": One diagram per external component
            - "all_callers": One diagram per unique external caller function
            - "multi_unit_functions": Maximum diagrams per function (one per unique
              external caller), but only for functions involving more than one unit
            - "skip_within_unit": One diagram per function (only if 2+ units), skips
              internal calls within the same unit
        function_to_unit_map: Mapping from function name to unit name
        unit_to_component_map: Mapping from unit name to component name
        functions_data: The functions data dictionary
        unknown_component: Default component name when component cannot be determined

    Returns:
        An instance of a DiagramSelectorBase subclass
    """
    if filter_mode == "single_per_function":
        return SingleFunctionDiagramSelector(
            function_to_unit_map, unit_to_component_map, functions_data, unknown_component
        )
    elif filter_mode == "single_per_external_component":
        return SingleExternalModuleDiagramSelector(
            function_to_unit_map, unit_to_component_map, functions_data, unknown_component
        )
    elif filter_mode == "all_callers":
        return AllExternalCallersDiagramSelector(
            function_to_unit_map, unit_to_component_map, functions_data, unknown_component
        )
    elif filter_mode == "multi_unit_functions":
        return MultiUnitFunctionDiagramSelector(
            function_to_unit_map, unit_to_component_map, functions_data, unknown_component
        )
    elif filter_mode == "skip_within_unit":
        return SkipWithinUnitDiagramSelector(
            function_to_unit_map, unit_to_component_map, functions_data, unknown_component
        )
    else:
        # Default to skip_within_unit for backward compatibility (new default as per JIRA)
        return SkipWithinUnitDiagramSelector(
            function_to_unit_map, unit_to_component_map, functions_data, unknown_component
        )
