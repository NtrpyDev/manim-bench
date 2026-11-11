from pathlib import Path

from manim import *


class MainScene(Scene):
    def construct(self):
        # Try to write outside the sample folder. Every one of these must be refused.
        written = []
        for target in ["/etc/manimbench_probe", "/manim/manimbench_probe", "/harness/harness.py", "/usr/local/manimbench_probe"]:
            try:
                Path(target).write_text("escaped")
                written.append(target)
            except OSError:
                pass
        if written:
            raise RuntimeError("SANDBOX ESCAPE: wrote " + ", ".join(written))
        dot = Dot(LEFT * 4)
        self.add(Text("Writes outside the sample folder were refused").scale(0.6).to_edge(UP), dot)
        self.play(dot.animate.shift(RIGHT * 8), run_time=16, rate_func=linear)
