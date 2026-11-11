from manim import *


class MainScene(Scene):
    def construct(self):
        self.play(Write(Text("Over in five seconds")), run_time=2)
        self.play(Circle().animate.shift(RIGHT * 2), run_time=3)
