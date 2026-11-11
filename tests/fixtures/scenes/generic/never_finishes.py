from manim import *


class MainScene(Scene):
    def construct(self):
        self.play(Write(Text("Stuck")))
        while True:
            pass
