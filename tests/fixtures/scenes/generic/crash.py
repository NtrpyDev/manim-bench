from manim import *


class MainScene(Scene):
    def construct(self):
        self.play(Write(Text("About to fail")))
        raise RuntimeError("deliberate failure for the test suite")
