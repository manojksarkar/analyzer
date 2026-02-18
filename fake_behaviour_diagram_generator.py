#!/usr/bin/env python3
"""Fake behaviour diagram generator for testing.

Two ways to use this module:

1) As a small library from `src/views/behaviour_diagram.py`:

   gen = FakeBehaviourGenerator(functions_path, modules_path, units_path)
   mermaid_paths = gen.generate_for_function(function_key, output_dir)

   The method will create 0..N Mermaid `.mmd` files for the given function
   under `output_dir` and return their full paths.

2) As a legacy CLI (kept for backwards compatibility with the old `scriptCmd` flow):

   python fake_behaviour_diagram_generator.py <functionKey> --model <modelPath>

   This prints a single sample Mermaid diagram to stdout.
"""

import argparse
import os
import random
import sys
from typing import List

SAMPLE_MERMAID = """flowchart TD
    A[Start] --> B{Check}
    B -->|yes| C[Process]
    B -->|no| D[Skip]
    C --> E[End]
    D --> E
"""


class FakeBehaviourGenerator:
    """Simple generator that always returns the same diagram for any function.

    In a real implementation this is where you would:
    - Read `functions.json`, `modules.json`, `units.json`
    - Analyse the specific function and its calls
    - Emit 0..N Mermaid diagrams based on that analysis
    """

    def __init__(self, functions_path: str, modules_path: str, units_path: str) -> None:
        # Paths are accepted for API completeness; we don't actually read them here.
        self.functions_path = functions_path
        self.modules_path = modules_path
        self.units_path = units_path

    def generate_for_function(self, function_key: str, output_dir: str) -> List[str]:
        """Create 0..N Mermaid files for `function_key` and return their paths.

        Fake implementation: randomly creates 0, 1, 2, 3, or 4 diagram files per function.
        """
        if not function_key:
            return []

        os.makedirs(output_dir, exist_ok=True)

        base = function_key.replace("|", "_").replace(" ", "_")
        n = random.randint(0, 4)
        paths = []

        for i in range(n):
            name = f"{base}_beh_{i}.mmd" if n > 1 else f"{base}_beh.mmd"
            mmd_path = os.path.join(output_dir, name)
            try:
                with open(mmd_path, "w", encoding="utf-8") as f:
                    f.write(SAMPLE_MERMAID)
                paths.append(mmd_path)
            except OSError:
                break

        return paths


def main() -> None:
    """Legacy CLI entrypoint: print a single diagram to stdout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("function_key", help="Function unique key (e.g. app|main|calculate|)")
    parser.add_argument("--model", required=True, help="Path to model directory (unused here)")
    _args = parser.parse_args()
    print(SAMPLE_MERMAID, end="")


if __name__ == "__main__":
    main()
