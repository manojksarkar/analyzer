"""Behavior diagram generator for C++ codebase analysis.

This component provides functionality to generate Mermaid sequence diagrams
showing the call flow through C++ source code, with units as nodes,
functions as edges, and units grouped by component.
"""

from .selector import (
    DiagramSelectorBase,
    SingleExternalModuleDiagramSelector,
    AllExternalCallersDiagramSelector,
    SingleFunctionDiagramSelector,
    SkipWithinUnitDiagramSelector,
    MultiUnitFunctionDiagramSelector,
    DiagramSelector,
    create_diagram_selector,
)
from .generator import SequenceDiagramGenerator
from .utils import safe_filename, load_json

__all__ = [
    # Selector classes
    "DiagramSelectorBase",
    "SingleExternalModuleDiagramSelector",
    "AllExternalCallersDiagramSelector",
    "SingleFunctionDiagramSelector",
    "SkipWithinUnitDiagramSelector",
    "MultiUnitFunctionDiagramSelector",
    "DiagramSelector",
    # Factory function
    "create_diagram_selector",
    # Main generator class
    "SequenceDiagramGenerator",
    # Utilities
    "safe_filename",
    "load_json",
]
