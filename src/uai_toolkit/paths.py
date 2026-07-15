"""Canonical path/env resolver — the PYTHON surface. Mirror of ai_env.sh.

Stdlib-only and never touches the ~/bin import shim — this is the one module that
must import before anything else. Resolution per var:
    explicit env var  >  config.toml  >  $AI_ROOT-derived default
config.toml is in the chain so the resolver works SHELL-LESS (native Windows can't
source ai_env.sh). AI_ROOT discovery is platform-aware. The default map is mirrored
in ai_env.sh; test_paths_consistency.py asserts the two agree for a given AI_ROOT
(with no config.toml / env overrides).

Merged model: var-map + two-surface anti-drift (Noctis) x platform-aware root
discovery + config.toml (Portage/uai_toolkit). Materializes to uai_toolkit/paths.py.
"""
import os
import sys
from pathlib import Path


def _load_toml(path: Path) -> dict:
    try:
        import tomllib                     # py3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib        # py3.9/3.10 (vendored in the toolkit)
        except ModuleNotFoundError:
            return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError:
        return {}


def _discover_root() -> Path:
    r = os.environ.get("AI_ROOT")                                   # 1. explicit env
    if r:
        return Path(r).expanduser()
    for base in (Path.cwd(), Path(__file__).resolve()):             # 2. repo marker
        for p in (base, *base.parents):
            if (p / "ai_general").is_dir() and (p / "CLAUDE.md").exists():
                return p
    ptr = Path.home() / ".ai_root"                                  # 3. pointer file
    if ptr.is_file():
        try:
            t = ptr.read_text().strip()
            if t:
                return Path(t).expanduser()
        except OSError:
            pass
    if os.name == "nt":                                             # 4. platform cfg dir
        base = os.environ.get("APPDATA")
        if base and (Path(base) / "ai_root").exists():
            return Path(base) / "ai_root"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        if (Path(xdg) / "ai_root").exists():
            return Path(xdg) / "ai_root"
    return Path.home() / "AI" / "ai_root"                           # 5. default


AI_ROOT = _discover_root()
_CFG = _load_toml(Path(os.environ.get("AI_CONFIG", AI_ROOT / "config.toml")))
_P = _CFG.get("paths", {}) if isinstance(_CFG, dict) else {}


def _v(name: str, default: Path) -> Path:
    v = os.environ.get(name) or _P.get(name) or _P.get(name.lower())   # env > toml > default
    return Path(v).expanduser() if v else default


# The canonical MAIN root: equals AI_ROOT on a normal install, but stays the
# production main when AI_ROOT is a devTree. Default = AI_ROOT (portable — no
# hardcode); the devTree tooling sets $AI_ROOT_MAIN when the two must differ.
AI_ROOT_MAIN = _v("AI_ROOT_MAIN", AI_ROOT)

# Derived (default under AI_ROOT, independently overridable):
AI_DATA          = _v("AI_DATA",          AI_ROOT / "ai_general" / "data")
AI_SCRIPTS       = _v("AI_SCRIPTS",       AI_ROOT / "ai_general" / "scripts")
AI_BIN           = _v("AI_BIN",           AI_ROOT / "ai_general" / "apps")   # where apps live
AI_LOGS          = _v("AI_LOGS",          AI_ROOT / "ai_general" / "logs")
AI_HOOKS         = _v("AI_HOOKS",         AI_DATA / "hooks")
AI_UAI_APP       = _v("AI_UAI_APP",       AI_BIN / "uai")                    # derives from AI_BIN
AI_CONTEXT_FILES = _v("AI_CONTEXT_FILES", AI_ROOT / "ai_general" / "ai_context_files")
# Independent (NOT derived from AI_ROOT):
AI_JSONL  = _v("AI_JSONL", Path.home() / ".claude" / "projects")   # caller appends the project slug
# AI_PYTHON: fixed default (matches ai_env.sh); the installer resolves it to the
# real interpreter (sys.executable at install) and writes it to config.toml/env.
AI_PYTHON = os.environ.get("AI_PYTHON") or _P.get("AI_PYTHON") or str(Path.home() / "myenv" / "bin" / "python")


# ── Accessors (python-only) ──────────────────────────────────────────────────
# These have NO shell counterpart, so they sit outside the ai_env.sh↔paths.py
# drift test (which compares only VAR VALUES). The toolkit depends on them:
# install.py wants ai_root(); file_access/tracker.py does dotted config lookups
# (get("file_access.db_path"), get("file_access.log_all_checks", True)) that no
# fixed path constant can cover.
def ai_root() -> Path:
    """AI_ROOT as a call, for callers that prefer an accessor over the constant."""
    return AI_ROOT


def config() -> dict:
    """The parsed config.toml as a dict (empty if absent/unparseable)."""
    return _CFG


def get(dotted: str, default=None):
    """Look up an arbitrary dotted key in config.toml, e.g. get("file_access.db_path").

    Free-form config keys (NOT the fixed AI_* path vars) — no constant covers them.
    Returns `default` if any segment along the path is missing.
    """
    cur = _CFG
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
