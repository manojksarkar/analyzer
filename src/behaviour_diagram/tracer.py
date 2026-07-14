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

    def _component_for_function(self, func: str) -> str:
        """Resolve the component name for a function key."""
        unit = self.function_to_unit.get(func)
        if unit:
            comp = self.unit_to_component.get(unit)
            if comp:
                return comp
        parts = (func or "").split("|")
        return parts[0] if parts and parts[0] else self.UNKNOWN_COMPONENT

    def external_callers(self, start_function: str) -> List[str]:
        """Return callers of start_function that live in a different component.

        Order is preserved from calledByIds so downstream diagrams line up with
        the caller list computed by the view.
        """
        fn = self.functions.get(start_function, {}) or {}
        current_component = self._component_for_function(start_function)
        result: List[str] = []
        for caller in fn.get("calledByIds", []) or []:
            if not caller:
                continue
            if self._component_for_function(caller) == current_component:
                continue
            result.append(caller)
        return result

    def trace_call_chain(self, start_function: str) -> List[Tuple[str, str]]:
        """
        Trace the complete call chain starting from a function.
        Traces backward through called_by to find external callers,
        then forward through calls to find all internal calls.

        Returns a list of (caller_key, callee_key) edges. Backward edges
        (external_caller -> start) come first, followed by forward edges
        discovered via a breadth-first walk over callsIds.
        """
        edges: List[Tuple[str, str]] = []
        seen: Set[Tuple[str, str]] = set()

        def _add(caller: str, callee: str) -> None:
            edge = (caller, callee)
            if edge not in seen:
                seen.add(edge)
                edges.append(edge)

        # Backward: external callers into the start function.
        for caller in self.external_callers(start_function):
            _add(caller, start_function)

        # Forward: every internal call reachable from the start function.
        visited: Set[str] = set()
        queue: List[str] = [start_function]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            cfn = self.functions.get(current, {}) or {}
            for callee in cfn.get("callsIds", []) or []:
                if not callee:
                    continue
                _add(current, callee)
                if callee not in visited:
                    queue.append(callee)

        return edges
