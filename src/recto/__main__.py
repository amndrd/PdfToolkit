"""Allow ``python -m recto`` alongside the installed ``recto`` script."""

from __future__ import annotations

import sys

from .cli.app import main

if __name__ == "__main__":
    sys.exit(main())
