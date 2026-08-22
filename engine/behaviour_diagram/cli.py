#!/usr/bin/env python3
"""CLI entry point for the behavior diagram generator."""

import argparse
import json
import sys

from .generator import SequenceDiagramGenerator


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="Generate Mermaid sequence diagrams from function call data"
    )
    parser.add_argument(
        "function",
        nargs="?",
        help="Name of the function to generate diagram for"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available functions"
    )
    parser.add_argument(
        "--components",
        default="model/components.json",
        help="Path to components.json (default: model/components.json)"
    )
    parser.add_argument(
        "--units",
        default="model/units.json",
        help="Path to units.json (default: model/units.json)"
    )
    parser.add_argument(
        "--functions",
        default="model/functions.json",
        help="Path to functions.json (default: model/functions.json)"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: print to stdout)"
    )
    parser.add_argument(
        "--all-callers",
        action="store_true",
        help="Generate separate diagrams for each external caller to the target"
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory for multiple diagrams (default: current directory)"
    )
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config.json (default: config/config.json)"
    )
    parser.add_argument(
        "--filter-mode",
        choices=["single_per_function", "single_per_external_component", "all_callers"],
        help="Override the filter mode from config"
    )

    args = parser.parse_args()

    # Load configuration from file
    config = None
    if args.config:
        try:
            with open(args.config, 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            # Config file not found, use defaults
            pass
        except json.JSONDecodeError:
            # Invalid JSON, use defaults
            pass

    # Override filter mode from command line if specified
    if args.filter_mode and config:
        if "views" not in config:
            config["views"] = {}
        if "sequenceDiagrams" not in config["views"]:
            config["views"]["sequenceDiagrams"] = {}
        config["views"]["sequenceDiagrams"]["filterMode"] = args.filter_mode

    # Initialize the generator with config
    generator = SequenceDiagramGenerator(
        args.components,
        args.units,
        args.functions,
        config
    )

    # List functions if requested
    if args.list:
        for func in sorted(generator.list_all_functions()):
            print(f"  - {func}")
        return

    # Check if function name is provided
    if not args.function:
        parser.print_help()
        sys.exit(1)

    # Generate the diagram(s)
    if args.all_callers:
        # Generate separate diagrams for each external caller
        generated_files, descriptions = generator.generate_all_diagrams(args.function, args.output_dir)
        if generated_files:
            print(f"\nGenerated {len(generated_files)} diagram(s) in '{args.output_dir}'")
    else:
        # Generate single diagram
        diagram = generator.generate_diagram(args.function)

        # Output the diagram
        if args.output:
            with open(args.output, 'w') as f:
                f.write(diagram)
        else:
            print(diagram)


if __name__ == "__main__":
    main()
