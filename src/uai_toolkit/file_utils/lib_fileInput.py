#!/usr/bin/env python3

import sys
import re
import os
import logging
import select
import subprocess
from pathlib import Path
from typing import List, Tuple, Union

# Assuming common_utils exists - adjust import as needed
# from common_utils import *

"""
Determines the file paths to be processed based on input source: command line, --from-file, or stdin.
Handles directories by listing their contents and processes stdin input, especially from dry-run output.

Args:
    args (Namespace): Parsed command-line arguments
    
Returns:
    tuple: A tuple containing a list of file paths to process and a boolean indicating dry-run mode
"""
# In lib_fileinput.py


def _normalize_input_path(raw_path: str) -> str:
    """Normalize incoming path strings from stdin or files."""

    cleaned = raw_path.strip().strip('"').strip("'")
    if not cleaned:
        return cleaned

    path = Path(cleaned).expanduser()
    try:
        # ``strict=False`` keeps non-existent paths while resolving ``..`` and ``.``
        path = path.resolve(strict=False)
    except OSError:
        # Fall back to the expanded path if resolution fails (e.g., permission errors)
        pass

    return str(path)


def read_clipboard_text() -> str:
    """Read text from the macOS clipboard.

    Uses ``pbpaste`` first and falls back to AppleScript for contexts where
    shell clipboard access behaves differently. Returns an empty string if no
    text clipboard content can be read.
    """
    clipboard_commands = [
        ["/usr/bin/pbpaste"],
        ["/usr/bin/osascript", "-e", "return the clipboard as text"],
    ]

    for command in clipboard_commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        if result.returncode == 0:
            return result.stdout

    return ""


def add_text_input_arguments(parser, *, file_flags=("-f", "--file")) -> None:
    """Add standard text input source arguments to an argparse parser.

    Scripts using this helper can read from a file, stdin, or clipboard/paste.
    ``-p`` and ``-v`` are both accepted as paste/clipboard shortcuts.
    """
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        *file_flags,
        dest="input_file",
        help="Read input text from this file.",
    )
    source_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read input text from stdin.",
    )
    source_group.add_argument(
        "-p",
        "--paste",
        action="store_true",
        help="Read input text from the clipboard.",
    )
    source_group.add_argument(
        "-v",
        "--clipboard",
        action="store_true",
        help="Read input text from the clipboard (alias for --paste).",
    )


def _stdin_ready(timeout_seconds: float = 0.05) -> bool:
    """Return whether stdin appears readable without blocking."""
    if sys.stdin.isatty():
        return False

    try:
        readable, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    except (OSError, ValueError):
        # If readiness probing is unavailable, treat non-TTY stdin as readable.
        return True

    return bool(readable)


def get_text_from_input(args, *, encoding: str = "utf-8", default_to_clipboard: bool = False) -> str:
    """Read text from file, stdin, or clipboard based on parsed args.

    Expected optional attributes on ``args``:
      - input_file or file: path to read
      - stdin: force stdin
      - paste or clipboard: force clipboard

    If no source is explicit and stdin has piped data ready, stdin is used even
    without ``--stdin``. In automation contexts such as Keyboard Maestro, stdin
    may be non-TTY but empty; when ``default_to_clipboard`` is true, empty
    implicit stdin falls through to clipboard instead of returning empty text.
    """
    input_file = getattr(args, "input_file", None) or getattr(args, "file", None)

    if getattr(args, "paste", False) or getattr(args, "clipboard", False):
        return read_clipboard_text()

    if input_file:
        with open(Path(input_file).expanduser(), "r", encoding=encoding) as file_obj:
            return file_obj.read()

    if getattr(args, "stdin", False):
        return sys.stdin.read()

    if _stdin_ready():
        stdin_text = sys.stdin.read()
        if stdin_text or not default_to_clipboard:
            return stdin_text

    if default_to_clipboard:
        return read_clipboard_text()

    return ""


def get_file_paths_from_input(args) -> Tuple[List[str], bool]:
    """
    Determine file paths based on input source priority:
    1. Positional arguments (directories/files on command line)
    2. --from-file option
    3. Stdin (piped input)

    Args:
        args: Parsed command-line arguments with optional 'directories' and 'from_file' attrs

    Returns:
        Tuple of (list of file paths, dry_run_detected boolean)
    """
    file_paths = []
    dry_run_detected = getattr(args, "dry_run", False)

    # Priority 1: Explicit positional arguments (directories/files)
    if hasattr(args, "directories") and args.directories:
        for path in args.directories:
            expanded_paths = expand_path(path)
            file_paths.extend(expanded_paths)
        return file_paths, dry_run_detected

    # Priority 2: --from-file option
    if hasattr(args, "from_file") and args.from_file:
        try:
            with open(args.from_file, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith("#"):  # Skip empty lines and comments
                        expanded_paths = expand_path(line)
                        file_paths.extend(expanded_paths)
        except FileNotFoundError:
            try:
                logging.error(f"File list not found: {args.from_file}")
            except:
                print(f"Error: File list not found: {args.from_file}", file=sys.stderr)
        except Exception as e:
            try:
                logging.error(f"Error reading file list {args.from_file}: {e}")
            except:
                print(f"Error reading file list {args.from_file}: {e}", file=sys.stderr)
        return file_paths, dry_run_detected

    # Priority 3: Stdin (piped input) - only if not a tty
    if not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            if "Dry-run:" in line and "->" in line:
                try:
                    logging.debug(
                        f"'Dry-run:' and '->' detected in piped input: {line}"
                    )
                except:
                    pass
                # Extract the filename after '->' for dry-run output
                modified_filename = line.split("->")[-1]
                file_paths.append(_normalize_input_path(modified_filename))
                dry_run_detected = True
            else:
                # Handle regular piped input (non-dry-run output)
                file_paths.append(_normalize_input_path(line))

    return file_paths, dry_run_detected


"""
Expand a single path, handling directories, wildcards, and individual files

Args:
    path (Union[str, Path]): Path to expand
    
Returns:
    List[str]: List of expanded file paths
"""


def expand_path(path: Union[str, Path]) -> List[str]:
    path_obj = Path(path).expanduser()
    expanded_paths = []

    if path_obj.is_dir():
        # Recursively list all files in the specified directory
        try:
            for root, _, files in os.walk(path_obj):
                for name in files:
                    file_path = os.path.join(root, name)
                    expanded_paths.append(file_path)
        except PermissionError:
            try:
                logging.warning(f"Permission denied accessing directory: {path_obj}")
            except:
                print(
                    f"Warning: Permission denied accessing directory: {path_obj}",
                    file=sys.stderr,
                )
    elif path_obj.exists() and path_obj.is_file():
        # Directly add the file path
        expanded_paths.append(str(path_obj))
    elif "*" in str(path) or "?" in str(path):
        # Handle wildcards using glob
        import glob

        matches = glob.glob(str(path))
        if matches:
            # Filter to only include files (not directories)
            expanded_paths.extend([match for match in matches if Path(match).is_file()])
        else:
            try:
                logging.warning(f"No files match pattern: {path}")
            except:
                print(f"Warning: No files match pattern: {path}", file=sys.stderr)
    else:
        try:
            logging.debug(f"Path does not exist: {path}")
        except:
            pass  # Don't print warnings for non-existent paths in case they're generated

    return expanded_paths


"""
Filter file paths by extension or pattern

Args:
    file_paths (List[str]): List of file paths to filter
    extensions (List[str], optional): List of allowed extensions (e.g., ['.md', '.txt'])
    patterns (List[str], optional): List of filename patterns to match
    
Returns:
    List[str]: Filtered list of file paths
"""


def filter_file_paths(
    file_paths: List[str], extensions: List[str] = None, patterns: List[str] = None
) -> List[str]:
    filtered_paths = []

    for file_path in file_paths:
        path_obj = Path(file_path)
        include_file = True

        # Filter by extension
        if extensions:
            if not any(path_obj.suffix.lower() == ext.lower() for ext in extensions):
                include_file = False

        # Filter by pattern
        if patterns and include_file:
            if not any(
                re.search(pattern, path_obj.name, re.IGNORECASE) for pattern in patterns
            ):
                include_file = False

        if include_file:
            filtered_paths.append(file_path)

    return filtered_paths


"""
Validate that file paths exist and are accessible

Args:
    file_paths (List[str]): List of file paths to validate
    
Returns:
    Tuple[List[str], List[str]]: Tuple of (valid_paths, invalid_paths)
"""


def validate_file_paths(file_paths: List[str]) -> Tuple[List[str], List[str]]:
    valid_paths = []
    invalid_paths = []

    for file_path in file_paths:
        path_obj = Path(file_path)
        if path_obj.exists() and path_obj.is_file():
            try:
                # Test if file is readable
                with open(path_obj, "r") as f:
                    pass
                valid_paths.append(file_path)
            except (PermissionError, UnicodeDecodeError):
                invalid_paths.append(file_path)
        else:
            invalid_paths.append(file_path)

    return valid_paths, invalid_paths


"""
Enhanced file input processing with filtering and validation

Args:
    args (Namespace): Parsed command-line arguments
    allowed_extensions (List[str], optional): Filter by extensions
    filename_patterns (List[str], optional): Filter by filename patterns
    validate_access (bool): Whether to validate file accessibility
    
Returns:
    tuple: (file_paths, dry_run_detected, invalid_paths)
"""


def get_file_paths_enhanced(
    args,
    allowed_extensions: List[str] = None,
    filename_patterns: List[str] = None,
    validate_access: bool = True,
) -> Tuple[List[str], bool, List[str]]:
    # Get basic file paths
    file_paths, dry_run_detected = get_file_paths_from_input(args)

    # Apply filtering
    if allowed_extensions or filename_patterns:
        file_paths = filter_file_paths(
            file_paths, allowed_extensions, filename_patterns
        )

    # Validate accessibility
    invalid_paths = []
    if validate_access:
        file_paths, invalid_paths = validate_file_paths(file_paths)

    return file_paths, dry_run_detected, invalid_paths
