from manim import *


class MainScene(Scene):
    def construct(self):
        # Prints far more than the log limit. The runner must keep only the start.
        line = "x" * 1000
        for _ in range(20000):
            print(line)
        dot = Dot(LEFT * 4)
        self.add(Text("Twenty megabytes of output").scale(0.6).to_edge(UP), dot)
        self.play(dot.animate.shift(RIGHT * 8), run_time=16, rate_func=linear)
