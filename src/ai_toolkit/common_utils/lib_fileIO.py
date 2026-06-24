#!/usr/bin/env python3
"""
Shared YAML/JSON file I/O with consistent error handling.

Usage:
    from ai_toolkit.common_utils.lib_fileIO import load_yaml, save_yaml, load_json, save_json
"""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def load_yaml(path, default=None):
    """Load YAML file. Returns default on error, prints to stderr."""
    if yaml is None:
        print("Error: PyYAML not installed", file=sys.stderr)
        return default
    filepath = Path(path)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return default
    except yaml.YAMLError as e:
        print(f"Error parsing YAML in {filepath}: {e}", file=sys.stderr)
        return default


def save_yaml(path, data, **dump_kwargs):
    """Save data as YAML. Returns True on success, False on error."""
    if yaml is None:
        print("Error: PyYAML not installed", file=sys.stderr)
        return False
    filepath = Path(path)
    dump_kwargs.setdefault("default_flow_style", False)
    dump_kwargs.setdefault("allow_unicode", True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, **dump_kwargs)
        return True
    except OSError as e:
        print(f"Error writing YAML to {filepath}: {e}", file=sys.stderr)
        return False


def load_json(path, default=None):
    """Load JSON file. Returns default on error, prints to stderr."""
    filepath = Path(path)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return default
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON in {filepath}: {e}", file=sys.stderr)
        return default


def save_json(path, data, **dump_kwargs):
    """Save data as JSON. Returns True on success, False on error."""
    filepath = Path(path)
    dump_kwargs.setdefault("indent", 2)
    dump_kwargs.setdefault("ensure_ascii", False)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
            f.write("\n")
        return True
    except OSError as e:
        print(f"Error writing JSON to {filepath}: {e}", file=sys.stderr)
        return False
