"""Shared pytest setup.

Makes the test suite runnable straight from a checkout, without requiring an
editable install first. Checkout tests must prefer this checkout's ``src/`` over
any older globally-installed wheel; installed-wheel checks run outside a source
tree and naturally fall through to the installed package.
"""
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def _remove_package_dir_import_shadow():
    """Undo legacy tests that expose ``src/uai_toolkit`` as top-level modules.

    That path makes this package's ``uai_toolkit/mcp`` directory shadow the real
    third-party ``mcp`` dependency, so later MCP tests see ``mcp`` but cannot
    import ``mcp.types``. The package source root above is the valid import root.
    """
    package_dir = str(Path(SRC) / "uai_toolkit")
    while package_dir in sys.path:
        sys.path.remove(package_dir)
    yield
