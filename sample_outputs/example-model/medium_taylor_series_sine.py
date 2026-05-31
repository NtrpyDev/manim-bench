from math import factorial
from manim import *


class MainScene(Scene):
    def construct(self):
        axes = Axes(x_range=[-4, 4, 1], y_range=[-2, 2, 1], x_length=8, y_length=4)
        sine = axes.plot(lambda x: np.sin(x), color=WHITE)
        polys = VGroup(
            axes.plot(lambda x: x, color=BLUE),
            axes.plot(lambda x: x - x**3 / factorial(3), color=GREEN),
            axes.plot(lambda x: x - x**3 / factorial(3) + x**5 / factorial(5), color=YELLOW),
            axes.plot(lambda x: x - x**3 / factorial(3) + x**5 / factorial(5) - x**7 / factorial(7), color=RED),
        )
        labels = VGroup(
            Text("sin(x)", font_size=24).to_edge(UP),
            Text("x", font_size=20).shift(LEFT * 3 + UP),
            Text("x - x^3/3!", font_size=20).shift(LEFT * 2 + DOWN * 2.7),
            Text("degree 5", font_size=20).shift(RIGHT * 1.2 + DOWN * 2.7),
            Text("degree 7", font_size=20).shift(RIGHT * 3 + UP),
            Text("error", font_size=20).shift(RIGHT * 2 + UP * 1.4),
            Text("x = 0", font_size=20).next_to(axes.c2p(0, 0), DOWN),
        )
        self.play(Create(axes), Create(sine), Write(labels[0]))
        for curve in polys:
            self.play(Create(curve), run_time=0.6)
        self.play(Write(labels[1:]))
        self.wait(1)
