#!/usr/bin/env python3
"""Command-line interface for behavior diagram generation."""

import argparse
import os
import sys

from .generator import SequenceDiagramGenerator


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="Generate Mermaid sequence diagrams from function call data")
    parser.add_argument(
        "function",
        nargs="?",
        help="Name of the function to generate diagram for")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available functions")
    parser.add_argument(
        "--components",
        default="model/components.json",
        help="Path to components.json (default: model/components.json)")
    parser.add_argument(
        "--units",
        default="model/units.json",
        help="Path to units.json (default: model/units.json)")
    parser.add_argument(
        "--functions",
        default="model/functions.json",
        help="Path to functions.json (default: model/functions.json)")
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: print to stdout)")
    args = parser.parse_args()

    generator = SequenceDiagramGenerator(
        args.components, args.units, args.functions)

    if args.list:
        for func_key in generator.list_functions():
            print(func_key)
        return

    if not args.function:
        parser.error("a function key is required (or use --list)")

    output_dir = args.output or os.getcwd()
    if os.path.splitext(output_dir)[1]:
        output_dir = os.path.dirname(output_dir) or os.getcwd()

    mmd_paths, descriptions = generator.generate_all_diagrams(args.function, output_dir)
    if not mmd_paths:
        print(f"No external-caller diagrams for {args.function!r}", file=sys.stderr)
        return

    for path, desc in zip(mmd_paths, descriptions):
        print(f"{path}\t{desc}")


if __name__ == "__main__":
    main()
