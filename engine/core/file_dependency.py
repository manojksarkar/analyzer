"""File dependency tracing for single-file document generation.

This module provides utilities to trace all units that are related to a target
file via the call graph, with full transitive closure (no depth limit).
"""

from collections import deque
from typing import Set


def trace_file_units(functions_data: dict, units_data: dict, target_file_rel: str) -> Set[str]:
    """Trace all units that depend on or are depended upon by target_file_rel.

    Uses BFS on the call graph with full transitive closure - no depth limit.
    Includes all units that can reach the target file, and all units reachable
    from the target file via function calls.

    Args:
        functions_data: The functions.json dictionary
        units_data: The units.json dictionary
        target_file_rel: The relative file path (from project root) to target

    Returns:
        Set of unit keys (module|unitname) that should be included:
        - The target file's unit
        - All units in callersUnits / calleesUnits of the target (transitive)

    Raises:
        ValueError: If target_file_rel maps to multiple units or no unit
    """
    from utils import make_unit_key

    target_unit_key = make_unit_key(target_file_rel)

    if target_unit_key not in units_data:
        return set()

    target_units: Set[str] = {target_unit_key}
    visited: Set[str] = set()
    queue: deque[str] = deque([target_unit_key])

    while queue:
        current_unit = queue.popleft()
        if current_unit in visited:
            continue
        visited.add(current_unit)

        current_data = units_data.get(current_unit)
        if not current_data:
            continue

        caller_units = set(current_data.get("callerUnits", []))
        callee_units = set(current_data.get("calleesUnits", []))

        for neighbor in caller_units | callee_units:
            if neighbor not in visited:
                queue.append(neighbor)
                target_units.add(neighbor)

    return target_units
