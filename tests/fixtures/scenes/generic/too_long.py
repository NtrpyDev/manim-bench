from manim import *


class MainScene(Scene):
    def construct(self):
        dot = Dot(LEFT * 5)
        self.add(Text("Runs past the limit").to_edge(UP), dot)
        self.play(dot.animate.shift(RIGHT * 10), run_time=59, rate_func=linear)
        self.play(dot.animate.shift(LEFT * 10), run_time=59, rate_func=linear)
        self.play(dot.animate.shift(RIGHT * 2), run_time=10, rate_func=linear)
