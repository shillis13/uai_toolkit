"""
Session state triggers — callbacks that fire on state changes.

Each trigger: (key, old_value, new_value, store) → None

Current triggers:
- role change: "developer" gained → provision dev environment
- features change: "write_code" gained → auto-add developer role
"""

import subprocess
import sys
from pathlib import Path

_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.common_utils.lib_logging import get_logger

log = get_logger(__name__)


DEV_TREES = Path.home() / "AI/devTrees"
CREATE_SCRIPT = Path(__file__).parent.parent / "dev/create_dev_env.sh"


def on_role_change(key: str, old_value, new_value, store):
    """When role gains 'developer', provision a dev environment."""
    old_roles = set(old_value if isinstance(old_value, list) else [])
    new_roles = set(new_value if isinstance(new_value, list) else [])

    gained_dev = "developer" in new_roles and "developer" not in old_roles
    lost_dev = "developer" not in new_roles and "developer" in old_roles

    if gained_dev:
        current_ai_root = store.get("ai_root") or ""
        if "devTrees/AI_ROOT_" in current_ai_root:
            log.info("Already in dev env: %s", current_ai_root)
            return

        session_id = store.session_id or "unknown"
        dev_id = session_id[:8]

        if not CREATE_SCRIPT.exists():
            log.error("create_dev_env.sh not found at %s", CREATE_SCRIPT)
            return

        try:
            result = subprocess.run(
                [str(CREATE_SCRIPT), "--id", dev_id],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.startswith("AI_ROOT="):
                        new_root = line.split("=", 1)[1]
                        store.set("ai_root", new_root)
                        log.info("Dev environment provisioned: %s", new_root)
                        break
            else:
                log.error("create_dev_env failed: %s", result.stderr)
        except Exception as e:
            log.error("Dev env creation error: %s", e)

    elif lost_dev:
        main_root = store.get("ai_root_main")
        if main_root:
            store.set("ai_root", main_root)
            log.info("Reverted to main AI_ROOT: %s", main_root)


def on_features_change(key: str, old_value, new_value, store):
    """When features gains 'write_code', ensure developer role is set."""
    new_features = set(new_value if isinstance(new_value, list) else [])
    current_roles = store.get("role") or []

    if "write_code" in new_features and "developer" not in current_roles:
        store.set("role", "developer")


def register_all_triggers(store):
    """Register all triggers on the store."""
    store.register_trigger("role", on_role_change)
    store.register_trigger("features", on_features_change)
