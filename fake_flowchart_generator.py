#!/usr/bin/env python3
"""Fake flowchart generator: reads functions.json, groups by unit, writes one JSON per unit.

Each unit JSON file contains an array of function info: name and flowchart (Mermaid string).

Usage:
  python fake_flowchart_generator.py --interface-json path/to/functions.json --std c++17 \\
    --clang-arg "-I/path/to/include" --out-dir output/flowcharts
"""

import argparse
import json
import os
import re
import sys

KEY_SEP = "|"

# Sample Mermaid flowchart used as fake content per function
SAMPLE_FLOWCHART = """flowchart TD
    A[Start] --> B{Check}
    B -->|yes| C[Process]
    B -->|no| D[Skip]
    C --> E[End]
    D --> E
"""


def safe_filename(s: str) -> str:
    """Filesystem-safe name (| and other unsafe chars -> _)."""
    return re.sub(r'[<>:"/\\|?*]', "_", s or "")


def function_id_to_unit_key(fid: str) -> str:
    """Extract unit key from function ID: module|unit|qualifiedName|params -> module|unit."""
    parts = (fid or "").split(KEY_SEP)
    if len(parts) >= 2:
        return parts[0] + KEY_SEP + parts[1]
    return "unknown|unknown"


def load_functions(interface_json_path: str) -> dict:
    """Load functions from JSON. Keys are function IDs, values are function objects."""
    with open(interface_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_flowchart_for_function(_func_data: dict) -> str:
    """Return a flowchart string for the function (fake: same diagram for all)."""
    return SAMPLE_FLOWCHART.strip()


def run(
    interface_json_path: str,
    out_dir: str,
    metadata_json_path: str = None,
    _std: str = "c++17",
    _clang_args: list = None,
) -> None:
    """Group functions by unit, write one JSON file per unit with name + flowchart per function."""
    functions = load_functions(interface_json_path)
    units = {}  # unit_key -> list of { name, flowchart }

    for fid, f in functions.items():
        unit_key = function_id_to_unit_key(fid)
        qualified = f.get("qualifiedName") or (fid.split(KEY_SEP)[2] if len(fid.split(KEY_SEP)) > 2 else fid or "?")
        # Simple name only (last segment after ::)
        name = (qualified.split("::")[-1]).strip() if "::" in (qualified or "") else (qualified or "?").strip()
        flowchart = build_flowchart_for_function(f)
        units.setdefault(unit_key, []).append({
            "name": name,
            "flowchart": flowchart,
        })

    os.makedirs(out_dir, exist_ok=True)

    for unit_key in sorted(units.keys()):
        # Filename: unit name only (no module prefix), e.g. main.json, utils.json
        unit_name = unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key
        base = safe_filename(unit_name)
        out_path = os.path.join(out_dir, f"{base}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(units[unit_key], f, indent=2)
        print(f"  {out_path} ({len(units[unit_key])} functions)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate per-unit JSON files with function name and flowchart from functions.json"
    )
    parser.add_argument(
        "--interface-json",
        required=True,
        metavar="PATH",
        help="Path to functions.json (interface data)",
    )
    parser.add_argument(
        "--metadata-json",
        default=None,
        metavar="PATH",
        help="Path to metadata.json (basePath, projectName, etc.)",
    )
    parser.add_argument(
        "--std",
        default="c++17",
        metavar="STD",
        help="C++ standard (e.g. c++17). Default: c++17",
    )
    parser.add_argument(
        "--clang-arg",
        action="append",
        default=[],
        metavar="ARG",
        dest="clang_args",
        help="Pass to clang (e.g. -I/path). Can be repeated.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        metavar="DIR",
        help="Output directory for unit JSON files",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.interface_json):
        print(f"Error: not found: {args.interface_json}", file=sys.stderr)
        sys.exit(1)
    if args.metadata_json and not os.path.isfile(args.metadata_json):
        print(f"Error: not found: {args.metadata_json}", file=sys.stderr)
        sys.exit(1)

    run(
        interface_json_path=args.interface_json,
        out_dir=args.out_dir,
        metadata_json_path=args.metadata_json,
        _std=args.std,
        _clang_args=args.clang_args or [],
    )


if __name__ == "__main__":
    main()
