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

    def __init__(self, function_to_unit_map: Dict[str, str],
                 unit_to_component_map: Dict[str, str],
                 functions_data: Dict,
                 unknown_component: str = "Unknown"):
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
            comp = self.unit_to_component.get(unit)
            if comp:
                return comp
        parts = (func or "").split("|")
        return parts[0] if parts and parts[0] else self.UNKNOWN_COMPONENT

    def _get_unit_for_function(self, func: str) -> str:
        """Get the unit key for a given function."""
        unit = self.function_to_unit.get(func)
        if unit:
            return unit
        parts = (func or "").split("|")
        return "|".join(parts[:2]) if len(parts) >= 2 else (func or "")

    def _callers(self, function_key: str) -> List[str]:
        """Return the raw caller keys for a function, order preserved."""
        fn = self.functions.get(function_key, {}) or {}
        return [c for c in (fn.get("calledByIds", []) or []) if c]

    def select_external_callers(self, function_key: str) -> List[str]:
        """
        Return the ordered list of caller keys that warrant a diagram.

        The base strategy selects every caller in a different component.
        Subclasses refine this behaviour.
        """
        current_component = self._get_component_for_function(function_key)
        return [
            caller for caller in self._callers(function_key)
            if self._get_component_for_function(caller) != current_component
        ]


class AllExternalCallersDiagramSelector(DiagramSelectorBase):
    """One diagram per external caller (callers from a different component)."""

    def select_external_callers(self, function_key: str) -> List[str]:
        return super().select_external_callers(function_key)


class SingleExternalModuleDiagramSelector(DiagramSelectorBase):
    """One diagram per distinct external component (first caller per component)."""

    def select_external_callers(self, function_key: str) -> List[str]:
        current_component = self._get_component_for_function(function_key)
        seen_components: Set[str] = set()
        result: List[str] = []
        for caller in self._callers(function_key):
            comp = self._get_component_for_function(caller)
            if comp == current_component or comp in seen_components:
                continue
            seen_components.add(comp)
            result.append(caller)
        return result


class SingleFunctionDiagramSelector(DiagramSelectorBase):
    """A single diagram: the first external caller only (or none)."""

    def select_external_callers(self, function_key: str) -> List[str]:
        externals = super().select_external_callers(function_key)
        return externals[:1]


class SkipWithinUnitDiagramSelector(DiagramSelectorBase):
    """One diagram per caller that lives outside the current unit."""

    def select_external_callers(self, function_key: str) -> List[str]:
        current_unit = self._get_unit_for_function(function_key)
        return [
            caller for caller in self._callers(function_key)
            if self._get_unit_for_function(caller) != current_unit
        ]


class MultiUnitFunctionDiagramSelector(DiagramSelectorBase):
    """One diagram per caller when callers span more than one external unit.

    If every external caller resolves to the same unit, no diagram is emitted.
    """

    def select_external_callers(self, function_key: str) -> List[str]:
        externals = super().select_external_callers(function_key)
        units = {self._get_unit_for_function(c) for c in externals}
        if len(units) <= 1:
            return []
        return externals


# Default strategy alias — one diagram per external caller, order preserved.
class DiagramSelector(AllExternalCallersDiagramSelector):
    """Default diagram selector (one diagram per external caller)."""


_SELECTOR_MODES = {
    "all_external_callers": AllExternalCallersDiagramSelector,
    "single_per_external_component": SingleExternalModuleDiagramSelector,
    "single_external_module": SingleExternalModuleDiagramSelector,
    "single_function": SingleFunctionDiagramSelector,
    "skip_within_unit": SkipWithinUnitDiagramSelector,
    "multi_unit_function": MultiUnitFunctionDiagramSelector,
    "default": DiagramSelector,
}


def create_diagram_selector(mode: Optional[str],
                            function_to_unit_map: Dict[str, str],
                            unit_to_component_map: Dict[str, str],
                            functions_data: Dict,
                            unknown_component: str = "Unknown") -> DiagramSelectorBase:
    """
    Factory for diagram selectors.

    Args:
        mode: selection strategy name (see _SELECTOR_MODES); falls back to the
            default all-external-callers strategy when unknown/None.
    """
    cls = _SELECTOR_MODES.get((mode or "default"), DiagramSelector)
    return cls(function_to_unit_map, unit_to_component_map, functions_data, unknown_component)
