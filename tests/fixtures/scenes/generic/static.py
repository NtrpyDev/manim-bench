from manim import *


class MainScene(Scene):
    def construct(self):
        # Something is on screen, but nothing ever changes after the first instant.
        self.add(Text("Nothing moves in this video"))
        self.wait(20)
