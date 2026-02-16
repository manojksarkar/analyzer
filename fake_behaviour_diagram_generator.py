#!/usr/bin/env python3
"""Fake behaviour diagram generator for testing. Returns same Mermaid for every function.
Usage: python fake_behaviour_diagram_generator.py <functionKey> --model <modelPath>
"""
import argparse
import sys

SAMPLE_MERMAID = """flowchart TD
    A[Start] --> B{Check}
    B -->|yes| C[Process]
    B -->|no| D[Skip]
    C --> E[End]
    D --> E
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("function_key", help="Function unique key (e.g. app|main|calculate|)")
    parser.add_argument("--model", required=True, help="Path to model directory")
    args = parser.parse_args()
    print(SAMPLE_MERMAID, end="")


if __name__ == "__main__":
    main()
