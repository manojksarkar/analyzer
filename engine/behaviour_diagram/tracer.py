#!/usr/bin/env python3
"""Call chain tracing logic for behavior diagram generation."""

from typing import Dict, List, Set, Tuple
from collections import defaultdict


class CallChainTracer:
    """Handles tracing of function call chains."""

    def __init__(self, function_to_unit_map: Dict[str, str],
                 unit_to_component_map: Dict[str, str],
                 functions_data: Dict,
                 unknown_component: str = "Unknown"):
        """
        Initialize the tracer with mapping data.

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
        call_chain = []
        visited_forward = set()
        visited_backward = set()

        # First, trace backward to find all callers (external entry points)
        def trace_backward(current_func: str):
            if current_func in visited_backward:
                return
            visited_backward.add(current_func)
            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for caller in func_data.get("calledByIds", []):
                call_chain.append((caller, current_func))
                trace_backward(caller)

        trace_backward(start_function)

        # Then, trace forward from the start function
        def trace_forward(current_func: str):
            if current_func in visited_forward:
                return
            visited_forward.add(current_func)

            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for callee in func_data.get("callsIds", []):
                call_chain.append((current_func, callee))
                trace_forward(callee)

        trace_forward(start_function)
        return call_chain

    def get_participants(self, call_chain: List[Tuple[str, str]]) -> Dict[str, Dict]:
        """
        Get all participants (units) involved in the call chain.

        Returns:
            Dictionary mapping unit_id to unit info
        """
        participants = {}
        functions_in_chain = set()

        # Collect all functions in the chain
        for caller, callee in call_chain:
            functions_in_chain.add(caller)
            functions_in_chain.add(callee)

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

        return participants

    def trace_forward_within_component(self, target_function: str,
                                       target_component: str,
                                       skip_within_unit: bool = False) -> List[Tuple[str, str]]:
        """
        Trace forward from a target function, only including calls within the target component.

        Args:
            target_function: Name of the target function
            target_component: Name of the target component
            skip_within_unit: If True, skip calls within the same unit

        Returns:
            List of tuples (caller_function, callee_function) for calls within the target component
        """
        call_chain = []
        visited = set()

        def trace_forward(current_func: str, origin: str):
            # `origin` is the nearest ancestor a cross-unit edge should be
            # attributed to. When intra-unit hops are skipped, origin stays put
            # so the downstream cross-unit edge bridges back to a function the
            # renderer actually starts from (the target or the previous
            # cross-unit boundary) rather than an orphaned intermediate.
            if current_func in visited:
                return
            visited.add(current_func)

            func_data = self.functions.get(current_func)
            if not func_data:
                return

            for callee in func_data.get("callsIds", []):
                callee_unit = self.function_to_unit.get(callee)
                if not callee_unit:
                    continue

                callee_component = self.unit_to_component.get(callee_unit, self.UNKNOWN_COMPONENT)

                # Skip calls within the same unit if skip_within_unit is True
                current_func_unit = self.function_to_unit.get(current_func)
                if skip_within_unit and current_func_unit and callee_unit == current_func_unit:
                    # Skip this call - it's within the same unit.
                    # Recurse but keep the same origin so a later cross-unit call
                    # is bridged back to origin (not this skipped intermediate).
                    trace_forward(callee, origin)
                    continue

                # Only include calls to the target component
                # Ignore calls to other external components including the caller's component
                if callee_component == target_component:
                    # Attribute the edge to origin (bridges skipped intra-unit
                    # hops), then advance origin to callee for further tracing.
                    call_chain.append((origin, callee))
                    trace_forward(callee, callee)

        trace_forward(target_function, target_function)

        return call_chain

    def get_external_callers(self, target_function: str) -> List[Tuple[str, str]]:
        """
        Get all external callers for a target function.

        Args:
            target_function: Name of the target function

        Returns:
            List of tuples (caller_function, caller_component) for each external caller
        """
        external_callers = []
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
                        external_callers.append((caller, caller_component))
                    trace_callers(caller)

        trace_callers(target_function)
        return external_callers

    def build_unit_order(self, backward_calls: List[Tuple[str, str]],
                         forward_calls: List[Tuple[str, str]]) -> Dict[str, int]:
        """
        Build ordering map for units based on their appearance in call chain.

        Args:
            backward_calls: List of backward (external) calls
            forward_calls: List of forward (internal) calls

        Returns:
            Dictionary mapping unit_id to its order index
        """
        unit_order = {}
        order_counter = 0

        # First, add external caller units in order
        for caller, callee in backward_calls:
            caller_unit = self.function_to_unit.get(caller)
            if caller_unit and caller_unit not in unit_order:
                unit_id = caller_unit.replace("|", "/")
                unit_order[unit_id] = order_counter
                order_counter += 1

        # Then add units in forward call order
        for caller, callee in forward_calls:
            for func in [caller, callee]:
                func_unit = self.function_to_unit.get(func)
                if func_unit:
                    unit_id = func_unit.replace("|", "/")
                    if unit_id not in unit_order:
                        unit_order[unit_id] = order_counter
                        order_counter += 1

        return unit_order

    def get_component_for_function(self, func: str) -> str:
        """Get the component name for a given function."""
        unit = self.function_to_unit.get(func)
        if unit:
            return self.unit_to_component.get(unit, self.UNKNOWN_COMPONENT)
        return self.UNKNOWN_COMPONENT
