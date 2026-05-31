#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from manimbench.cli import main


if __name__ == "__main__":
    # Default behavior compares only models that have all selected task outputs.
    # Pass extra args through, for example:
    #   python run_comparison.py --include-partial --sandbox local
    raise SystemExit(main(["compare-ready", *sys.argv[1:]]))
