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
    if len(sys.argv) > 1:
        raise SystemExit(main(["create-workspaces", *sys.argv[1:]]))
    raise SystemExit(main(["create-workspaces", "--force"]))
