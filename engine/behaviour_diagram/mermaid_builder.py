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

    @staticmethod
    def participant_id(unit_key: str) -> str:
        """Return a Mermaid-safe participant identifier for a unit key."""
        safe = "".join(c if c.isalnum() else "_" for c in (unit_key or ""))
        return "u_" + safe if safe else "u_unknown"

    def build_sequence_diagram(self,
                               participants: List[Tuple[str, str]],
                               messages: List[Tuple[str, str, str]],
                               title: Optional[str] = None) -> str:
        """
        Assemble a Mermaid sequenceDiagram from participants and messages.

        Args:
            participants: ordered list of (participant_id, label)
            messages: ordered list of (from_id, to_id, text)
            title: optional diagram title (rendered as a comment for compatibility)

        Returns:
            The Mermaid diagram source as a string.
        """
        lines: List[str] = ["sequenceDiagram"]
        if title:
            lines.append(f"    %% {title}")
        lines.append("    autonumber")

        seen_ids = set()
        for pid, label in participants:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            lines.append(f"    participant {pid} as {label}")

        for frm, to, text in messages:
            lines.append(f"    {frm}->>{to}: {text}")

        return "\n".join(lines) + "\n"
