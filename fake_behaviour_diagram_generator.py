#!/usr/bin/env python3
"""Fake behaviour diagram generator for testing.

Two ways to use this module:

1) As a small library from `src/views/behaviour_diagram.py`:

   gen = FakeBehaviourGenerator(modules_path, units_path, functions_path)
   mermaid_paths = gen.generate_all_diagrams(function_key, output_dir)

   Takes paths to model JSON files (modules, units, functions).
   Output: one .mmd file per external caller, named
   current_function_key__caller_function_key.mmd (current gets called by external unit)
   e.g. app_main_calculate___math_utils_add_int_int.mmd
   (no .mmd when the function has no external callers).

2) As a legacy CLI (kept for backwards compatibility with the old `scriptCmd` flow):

   python fake_behaviour_diagram_generator.py <functionKey> --model <modelPath>

   This prints a single sample Mermaid diagram to stdout.
"""

import argparse
import json
import os
import sys
from typing import List

_proj = os.path.dirname(os.path.abspath(__file__))
if _proj not in sys.path:
    sys.path.insert(0, _proj)
from utils import safe_filename

SAMPLE_MERMAID = """flowchart TD
    A[Start] --> B{Check}
    B -->|yes| C[Process]
    B -->|no| D[Skip]
    C --> E[End]
    D --> E
"""


class FakeBehaviourGenerator:
    """Fake generator that emits one .mmd per (current_function, caller_function).
    Current unit gets called by external unit.

    Takes paths to modules.json, units.json, functions.json.
    Output naming: current_key__caller_key.mmd (sanitized)
    No output when the function has no external callers.
    """

    def __init__(self, modules_path: str, units_path: str, functions_path: str) -> None:
        self.modules_path = modules_path
        self.units_path = units_path
        self.functions_path = functions_path

    def generate_all_diagrams(self, function_key: str, output_dir: str) -> List[str]:
        """Create one .mmd per external caller, named current_key__caller_key.mmd.
        Returns empty list if no external callers.
        """
        if not function_key:
            return []

        os.makedirs(output_dir, exist_ok=True)

        functions_data = {}
        if os.path.isfile(self.functions_path):
            try:
                with open(self.functions_path, "r", encoding="utf-8") as f:
                    functions_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        self_module = (function_key or "").split("|")[0] if "|" in (function_key or "") else ""
        called_by_ids = functions_data.get(function_key, {}).get("calledByIds", []) or []
        paths = []

        for caller_key in called_by_ids:
            caller_module = (caller_key or "").split("|")[0] if "|" in (caller_key or "") else ""
            if caller_module == self_module:
                continue
            safe_c = safe_filename((function_key or "").replace("|", "_"))
            safe_k = safe_filename((caller_key or "").replace("|", "_"))
            name = f"{safe_c}__{safe_k}.mmd"
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
