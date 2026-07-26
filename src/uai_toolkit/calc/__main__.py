"""Enable ``python -m calc``."""

import sys

from uai_toolkit.calc.cli import main

if __name__ == "__main__":
    sys.exit(main())
