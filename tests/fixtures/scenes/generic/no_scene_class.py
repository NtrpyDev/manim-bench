from manim import *


class Lesson(Scene):
    def construct(self):
        self.play(Write(Text("The class has the wrong name")))
        self.wait(20)
