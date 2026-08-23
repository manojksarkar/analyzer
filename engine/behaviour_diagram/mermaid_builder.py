#!/usr/bin/env python3
"""Mermaid diagram building logic for behavior diagram generation."""

from typing import Dict, List, Tuple, Optional
from collections import defaultdict


class MermaidBuilder:
    """Builds Mermaid sequence diagrams."""

    # Color scheme constants
    CURRENT_COMPONENT_COLOR = "skyblue"
    EXTERNAL_COMPONENT_COLOR = "lightgreen"
    DEFAULT_COMPONENT_COLOR = "rgb(100, 100, 100)"
    UNKNOWN_COMPONENT = "Unknown"

    def __init__(self, current_component: Optional[str] = None):
        """
        Initialize the Mermaid builder.

        Args:
            current_component: The component name for the "current" context (for coloring)
        """
        self.current_component = current_component

    def get_component_color(self, component_name: str) -> str:
        """
        Get color for a component.

        Returns skyblue for current component, lightgreen for external components.
        """
        if self.current_component and component_name == self.current_component:
            return self.CURRENT_COMPONENT_COLOR
        else:
            return self.EXTERNAL_COMPONENT_COLOR

    def build_diagram_lines(self,
                            component_participants: Dict[str, List[Tuple[str, Dict]]],
                            external_caller_component: Optional[str],
                            unit_order: Dict[str, int]) -> List[str]:
        """
        Build the initial diagram lines with component boxes and participants.

        Args:
            component_participants: Dictionary mapping component names to (unit_id, unit_info) tuples
            external_caller_component: The external caller's component name (goes first)
            unit_order: Order mapping for units within each component

        Returns:
            List of diagram lines
        """
        diagram_lines = ["sequenceDiagram"]

        # Add component boxes and participants
        self._add_component_boxes(diagram_lines, component_participants, external_caller_component, unit_order)
        diagram_lines.append("")

        return diagram_lines

    def _add_component_boxes(self,
                             diagram_lines: List[str],
                             component_participants: Dict[str, List[Tuple[str, Dict]]],
                             external_caller_component: Optional[str],
                             unit_order: Dict[str, int]) -> None:
        """
        Add component boxes and participants to diagram.

        Args:
            diagram_lines: List to append diagram lines to
            component_participants: Dictionary mapping component names to (unit_id, unit_info) tuples
            external_caller_component: The external caller's component name (goes first)
            unit_order: Order mapping for units within each component
        """
        # Sort units within each component by their call order
        for component in component_participants:
            component_participants[component].sort(key=lambda x: unit_order.get(x[0], float('inf')))

        # Add external caller's component first
        if external_caller_component and external_caller_component in component_participants:
            color = self.get_component_color(external_caller_component)
            diagram_lines.append(f"    box {color} {external_caller_component}")
            for unit_id, _ in component_participants[external_caller_component]:
                diagram_lines.append(f"        participant {unit_id} as {unit_id}")
            diagram_lines.append("    end")

        # Add remaining components
        for component, units in component_participants.items():
            if component != external_caller_component:
                color = self.get_component_color(component)
                diagram_lines.append(f"    box {color} {component}")
                for unit_id, _ in units:
                    diagram_lines.append(f"        participant {unit_id} as {unit_id}")
                diagram_lines.append("    end")

    def add_backward_calls(self,
                           diagram_lines: List[str],
                           backward_calls: List[Tuple[str, str]],
                           behavior_descriptions: List[str],
                           function_to_unit: Dict[str, str],
                           get_function_name_func: callable) -> None:
        """
        Add backward call arrows (external entry points) to the diagram.

        Args:
            diagram_lines: List to append diagram lines to
            backward_calls: List of backward (external) calls
            behavior_descriptions: List to append behavior descriptions to
            function_to_unit: Mapping from function name to unit name
            get_function_name_func: Function to get display name from function key
        """
        for caller, callee in backward_calls:
            caller_unit = function_to_unit.get(caller)
            callee_unit = function_to_unit.get(callee)
            if not caller_unit or not callee_unit:
                continue

            caller_id = caller_unit.replace("|", "/")
            callee_id = callee_unit.replace("|", "/")
            caller_name = get_function_name_func(caller)
            callee_name = get_function_name_func(callee)

            diagram_lines.append(f"    {caller_id}->>{callee_id}: {callee_name}()")
            diagram_lines.append(f"    activate {callee_id}")
            behavior_descriptions.append(f"{caller_name} calls {callee_name}")

    def add_forward_calls_recursive(self,
                                    func: str,
                                    call_tree: Dict[str, List[str]],
                                    diagram_lines: List[str],
                                    behavior_descriptions: List[str],
                                    function_to_unit: Dict[str, str],
                                    get_function_name_func: callable,
                                    get_call_description_func: callable) -> None:
        """
        Recursively add forward call arrows with activation tracking.

        Args:
            func: Current function name
            call_tree: Dictionary mapping caller to list of callees
            diagram_lines: List to append diagram lines to
            behavior_descriptions: List to append behavior descriptions to
            function_to_unit: Mapping from function name to unit name
            get_function_name_func: Function to get display name from function key
            get_call_description_func: Function to get call description
        """
        for callee in call_tree.get(func, []):
            caller_unit = function_to_unit.get(func)
            callee_unit = function_to_unit.get(callee)
            if not caller_unit or not callee_unit:
                continue

            caller_id = caller_unit.replace("|", "/")
            callee_id = callee_unit.replace("|", "/")
            callee_name = get_function_name_func(callee)
            caller_name = get_function_name_func(func)

            # Add call arrow
            diagram_lines.append(f"    {caller_id}->>{callee_id}: {callee_name}()")
            diagram_lines.append(f"    activate {callee_id}")
            behavior_descriptions.append(get_call_description_func(func, callee))

            # Recursively add nested calls
            self.add_forward_calls_recursive(
                callee, call_tree, diagram_lines, behavior_descriptions,
                function_to_unit, get_function_name_func, get_call_description_func
            )

            # Add return after nested calls
            diagram_lines.append(f"    {callee_id}-->>{caller_id}: Return")
            diagram_lines.append(f"    deactivate {callee_id}")
            behavior_descriptions.append(f"{callee_name} returns to {caller_name}")

    def add_backward_returns(self,
                             diagram_lines: List[str],
                             backward_calls: List[Tuple[str, str]],
                             behavior_descriptions: List[str],
                             function_to_unit: Dict[str, str],
                             get_function_name_func: callable) -> None:
        """
        Add return arrows for backward calls.

        Args:
            diagram_lines: List to append diagram lines to
            backward_calls: List of backward (external) calls
            behavior_descriptions: List to append behavior descriptions to
            function_to_unit: Mapping from function name to unit name
            get_function_name_func: Function to get display name from function key
        """
        for caller, callee in backward_calls:
            caller_unit = function_to_unit.get(caller)
            callee_unit = function_to_unit.get(callee)
            if not caller_unit or not callee_unit:
                continue

            caller_id = caller_unit.replace("|", "/")
            callee_id = callee_unit.replace("|", "/")
            callee_name = get_function_name_func(callee)
            caller_name = get_function_name_func(caller)

            diagram_lines.append(f"    {callee_id}-->>{caller_id}: Return")
            diagram_lines.append(f"    deactivate {callee_id}")
            behavior_descriptions.append(f"{callee_name} returns to {caller_name}")

    def build_diagram_for_caller(self,
                                 component_participants: Dict[str, List[Tuple[str, Dict]]],
                                 caller_component: str,
                                 call_chain: List[Tuple[str, str]],
                                 target_function: str,
                                 caller_function: str,
                                 function_to_unit: Dict[str, str],
                                 get_function_name_func: callable,
                                 get_call_description_func: callable) -> Tuple[List[str], List[str]]:
        """
        Build a Mermaid diagram for a specific caller to a target function.

        Args:
            component_participants: Dictionary mapping component names to (unit_id, unit_info) tuples
            caller_component: The caller's component name
            call_chain: List of (caller, callee) tuples representing the call chain
            target_function: The target function key
            caller_function: The caller function key
            function_to_unit: Mapping from function name to unit name
            get_function_name_func: Function to get display name from function key
            get_call_description_func: Function to get call description

        Returns:
            Tuple of (diagram_lines, behavior_descriptions)
        """
        # Build unit ordering map
        unit_order = self._build_unit_order_for_caller(
            call_chain, caller_function, target_function, function_to_unit
        )

        # Sort units within each component by their call order
        for component in component_participants:
            component_participants[component].sort(key=lambda x: unit_order.get(x[0], float('inf')))

        # Build the diagram
        diagram_lines = ["sequenceDiagram"]

        # Add component boxes and participants - external caller's component first
        if caller_component in component_participants:
            color = self.get_component_color(caller_component)
            diagram_lines.append(f"    box {color} {caller_component}")

            for unit_id, info in component_participants[caller_component]:
                diagram_lines.append(f"        participant {unit_id} as {unit_id.split('/')[1]}")

            diagram_lines.append("    end")

        # Then add the remaining components
        for component, units in component_participants.items():
            if component != caller_component:
                color = self.get_component_color(component)
                diagram_lines.append(f"    box {color} {component}")

                for unit_id, info in units:
                    diagram_lines.append(f"        participant {unit_id} as {unit_id.split('/')[1]}")

                diagram_lines.append("    end")

        diagram_lines.append("")  # Empty line for separation

        # Build a call tree
        call_tree = defaultdict(list)
        for caller, callee in call_chain:
            call_tree[caller].append(callee)

        behavior_descriptions = []

        # Add the initial call from external caller to target function
        caller_unit = function_to_unit.get(caller_function)
        target_unit = function_to_unit.get(target_function)
        if caller_unit and target_unit:
            caller_id = caller_unit.replace("|", "/")
            target_id = target_unit.replace("|", "/")
            diagram_lines.append(f"    {caller_id}->>{target_id}: {get_function_name_func(target_function)}()")
            diagram_lines.append(f"    activate {target_id}")
            behavior_descriptions.append(get_call_description_func(caller_function, target_function))

        # Add forward calls with proper activation tracking
        activation_stack = []
        def add_calls_recursive(func: str):
            """Recursively add calls and track activation."""
            for callee in call_tree.get(func, []):
                caller_unit = function_to_unit.get(func)
                callee_unit = function_to_unit.get(callee)
                if not caller_unit or not callee_unit:
                    continue
                caller_id = caller_unit.replace("|", "/")
                callee_id = callee_unit.replace("|", "/")
                diagram_lines.append(f"    {caller_id}->>{callee_id}: {get_function_name_func(callee)}()")
                diagram_lines.append(f"    activate {callee_id}")
                activation_stack.append((caller_id, callee_id))
                behavior_descriptions.append(get_call_description_func(func, callee))
                # Recursively add nested calls
                add_calls_recursive(callee)
                # Add return after all nested calls
                diagram_lines.append(f"    {callee_id}-->>{caller_id}: Return")
                diagram_lines.append(f"    deactivate {callee_id}")
                behavior_descriptions.append(f"{get_function_name_func(callee)} returns to {get_function_name_func(func)}")

        # Start from the target_function and add all forward calls
        add_calls_recursive(target_function)

        # Add return from target function to external caller
        if caller_unit and target_unit:
            diagram_lines.append(f"    {target_id}-->>{caller_id}: Return")
            diagram_lines.append(f"    deactivate {target_id}")
            behavior_descriptions.append(f"{get_function_name_func(target_function)} returns to {get_function_name_func(caller_function)}")

        return diagram_lines, behavior_descriptions

    def _build_unit_order_for_caller(self,
                                     call_chain: List[Tuple[str, str]],
                                     caller_function: str,
                                     target_function: str,
                                     function_to_unit: Dict[str, str]) -> Dict[str, int]:
        """
        Build ordering map for units based on their call order for a specific caller.

        Args:
            call_chain: List of (caller, callee) tuples
            caller_function: The caller function key
            target_function: The target function key
            function_to_unit: Mapping from function name to unit name

        Returns:
            Dictionary mapping unit_id to its order index
        """
        unit_order = {}
        order_counter = 0

        # First, add the external caller unit
        caller_unit = function_to_unit.get(caller_function)
        if caller_unit:
            caller_id = caller_unit.replace("|", "/")
            unit_order[caller_id] = order_counter
            order_counter += 1

        # Then add units in forward call order
        for caller, callee in call_chain:
            caller_unit = function_to_unit.get(caller)
            callee_unit = function_to_unit.get(callee)

            if caller_unit:
                caller_id = caller_unit.replace("|", "/")
                if caller_id not in unit_order:
                    unit_order[caller_id] = order_counter
                    order_counter += 1

            if callee_unit:
                callee_id = callee_unit.replace("|", "/")
                if callee_id not in unit_order:
                    unit_order[callee_id] = order_counter
                    order_counter += 1

        return unit_order

    def get_external_caller_component(self,
                                      backward_calls: List[Tuple[str, str]],
                                      start_function: str,
                                      function_to_unit: Dict[str, str],
                                      unit_to_component: Dict[str, str]) -> Optional[str]:
        """
        Get the component of the first external caller, or start function's component if none.

        Args:
            backward_calls: List of backward (external) calls
            start_function: The start function key
            function_to_unit: Mapping from function name to unit name
            unit_to_component: Mapping from unit name to component name

        Returns:
            The component name of the external caller, or the start function's component
        """
        if backward_calls:
            first_caller = backward_calls[0][0]
            caller_unit = function_to_unit.get(first_caller)
            if caller_unit:
                return unit_to_component.get(caller_unit, self.UNKNOWN_COMPONENT)

        start_unit = function_to_unit.get(start_function)
        if start_unit:
            return unit_to_component.get(start_unit, self.UNKNOWN_COMPONENT)
        return None
