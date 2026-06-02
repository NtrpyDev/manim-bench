from __future__ import annotations

from manimbench.tui.app import ManimBenchApp


def launch() -> int:
    app = ManimBenchApp()
    app.run()
    return 0


__all__ = ["ManimBenchApp", "launch"]
