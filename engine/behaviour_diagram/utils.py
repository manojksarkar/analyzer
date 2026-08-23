#!/usr/bin/env python3
"""Utility functions for behavior diagram generation."""

import json
import re
import sys
from typing import Dict


def safe_filename(s: str) -> str:
    """
    Filesystem-safe name (| and other unsafe chars -> _).

    Includes , & ; to avoid Windows cmd parsing issues when paths are passed to mmdc.
    """
    return re.sub(r'[<>:"/\\|?*,&;]', "_", s or "")


def load_json(filepath: str) -> Dict:
    """
    Load JSON data from file.

    Args:
        filepath: Path to the JSON file

    Returns:
        The loaded JSON data as a dictionary

    Note:
        Exits with status code 1 if file not found or invalid JSON
    """
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(1)
    except json.JSONDecodeError as e:
        sys.exit(1)
