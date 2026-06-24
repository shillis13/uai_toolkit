"""Utilities for running a repository-wide byte-compilation check.

The :func:`run` function performs the heavy lifting and can be reused by
other tooling. A matching CLI is exposed via ``python -m
dev_utils.compile_check`` (with ``PYTHONPATH=src``) and the ``scripts``
wrapper to align with the rest of the repository.
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import logging
import os
import py_compile
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Directories such as ``tmp`` and ``third_party`` contain generated or vendored
# code that should not block compilation checks.  ``__pycache__`` and similar
# entries are ignored for performance.
DEFAULT_EXCLUDES: Tuple[str, ...] = (
    "__pycache__",
    "*.pyc",
    ".git",
    ".venv",
    "tmp",
    "third_party",
)

DEFAULT_PATHS: Tuple[str, ...] = ("src",)

Result = Dict[str, object]


def _has_glob(path: str) -> bool:
    return any(char in path for char in "*?[]")


def _format_path(path: Path) -> str:
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path
    try:
        relative_to_repo = resolved.relative_to(REPO_ROOT)
    except ValueError:
        relative_to_repo = None
    if relative_to_repo is not None:
        return str(relative_to_repo)
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _should_exclude(path: Path, patterns: Sequence[str]) -> bool:
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        relative = None

    for pattern in patterns:
        candidates = [str(resolved), resolved.name]
        if relative is not None:
            rel_str = str(relative)
            candidates.extend([rel_str, relative.name])
            candidates.extend(relative.parts)
        else:
            if pattern in {"__pycache__", "*.pyc"}:
                candidates.extend(resolved.parts)
        if any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates):
            return True
    return False


def _iter_python_files(
    targets: Sequence[Path],
    recursive: bool,
    patterns: Sequence[str],
) -> Iterator[Path]:
    seen: set[Path] = set()
    for target in targets:
        if not target.exists():
            continue
        if target.is_file():
            if target.suffix == ".py" and not _should_exclude(target, patterns):
                resolved = target.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield target
            continue
        if not target.is_dir():
            continue
        if _should_exclude(target, patterns):
            continue
        if recursive:
            for root, dirs, files in os.walk(target):
                root_path = Path(root)
                if _should_exclude(root_path, patterns):
                    dirs[:] = []
                    continue
                dirs[:] = [
                    d for d in dirs if not _should_exclude(root_path / d, patterns)
                ]
                for name in files:
                    file_path = root_path / name
                    if file_path.suffix == ".py" and not _should_exclude(
                        file_path, patterns
                    ):
                        resolved = file_path.resolve()
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        yield file_path
        else:
            for child in target.iterdir():
                if (
                    child.is_file()
                    and child.suffix == ".py"
                    and not _should_exclude(child, patterns)
                ):
                    resolved = child.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    yield child


def _expand_paths(raw_paths: Sequence[str]) -> Tuple[List[Path], List[Path]]:
    expanded: List[Path] = []
    missing: List[Path] = []
    for raw in raw_paths:
        path_str = str(raw)
        matches: List[str]
        if _has_glob(path_str):
            matches = glob.glob(path_str, recursive=True)
            if not matches:
                missing.append(Path(path_str))
            for match in matches:
                expanded.append(Path(match))
            continue
        candidate = Path(path_str)
        if not candidate.exists():
            missing.append(candidate)
        expanded.append(candidate)
    return expanded, missing


def _build_missing_result(path: Path) -> Result:
    return {
        "path": _format_path(path),
        "ok": False,
        "error": {
            "type": "FileNotFoundError",
            "message": "Path not found",
            "line": None,
            "column": None,
        },
    }


def _compile_file(path: Path) -> Result:
    try:
        py_compile.compile(str(path), doraise=True)
        return {"path": _format_path(path), "ok": True}
    except py_compile.PyCompileError as exc:
        err = exc.exc_value  # type: ignore[attr-defined]
        message = getattr(err, "msg", str(err))
        line = getattr(err, "lineno", None)
        column = getattr(err, "offset", None)
        error_type = getattr(err, "__class__", type(err)).__name__
        LOGGER.debug("Compilation failed for %s: %s", path, message)
        return {
            "path": _format_path(path),
            "ok": False,
            "error": {
                "type": error_type,
                "message": message,
                "line": line,
                "column": column,
            },
        }


def _emit_human(results: Sequence[Result], all_ok: bool, quiet: bool, stream) -> None:
    for result in results:
        if result.get("ok"):
            if quiet:
                continue
            stream.write(f"{result['path']}: OK\n")
            continue
        error: Dict[str, object] = result.get("error", {})  # type: ignore[assignment]
        line_info = ""
        line = error.get("line")
        column = error.get("column")
        if line is not None:
            line_info = f" (line {line}"
            if column is not None:
                line_info += f":{column}"
            line_info += ")"
        message = error.get("message", "")
        err_type = error.get("type", "")
        stream.write(f"{result['path']}: FAIL — {err_type}: {message}{line_info}\n")
    return None


def run(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    recursive: bool = False,
    excludes: Sequence[str] = (),
    quiet: bool = False,
    json_output: bool = False,
    stream=None,
    use_default_excludes: bool = True,
) -> Tuple[List[Result], bool]:
    """Run the byte-compilation check.

    Args:
        paths: Files, directories, or glob patterns to inspect. Defaults to ``("src",)``.
        recursive: Walk directories recursively when true.
        excludes: Additional glob patterns to skip.
        quiet: Suppress ``OK`` lines in human-readable output.
        json_output: Emit JSON when ``stream`` is provided.
        stream: Optional IO object used for output.  When ``None`` nothing is printed.
        use_default_excludes: Include :data:`DEFAULT_EXCLUDES` when filtering targets.

    Returns:
        ``(results, all_ok)`` where ``results`` is a list of dictionaries and ``all_ok``
        indicates whether every compiled file succeeded.
    """
    expanded, missing = _expand_paths(paths)
    patterns: List[str] = []
    if use_default_excludes:
        patterns.extend(DEFAULT_EXCLUDES)
    patterns.extend(excludes)

    results: List[Result] = []
    all_ok = True

    for missing_path in missing:
        result = _build_missing_result(missing_path)
        results.append(result)
        all_ok = False

    files = list(_iter_python_files(expanded, recursive, patterns))
    files.sort(key=lambda p: _format_path(p))

    for file_path in files:
        result = _compile_file(file_path)
        if not result["ok"]:
            all_ok = False
        results.append(result)

    results.sort(key=lambda item: item["path"])

    if stream is not None:
        if json_output:
            payload = {"results": results, "all_ok": all_ok}
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        else:
            _emit_human(results, all_ok, quiet, stream)
        stream.flush()

    return results, all_ok


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Byte-compile Python files to catch syntax errors early.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_PATHS),
        help="Files, directories, or glob patterns to check (default: src).",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recurse into subdirectories when targets are directories.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude (repeatable).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress OK lines in text output.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable the built-in exclude list (tmp, third_party, __pycache__, etc.).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    results, all_ok = run(
        args.paths,
        recursive=args.recursive,
        excludes=tuple(args.exclude or ()),
        quiet=args.quiet,
        json_output=args.json,
        stream=sys.stdout,
        use_default_excludes=not args.no_default_excludes,
    )
    return 0 if all_ok else 1


if __name__ == "__main__":  # pragma: no cover - convenience for direct execution
    raise SystemExit(main())
