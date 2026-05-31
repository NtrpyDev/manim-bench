from manim import *


class MainScene(Scene):
    def construct(self):
        axes = Axes(x_range=[-1, 5, 1], y_range=[-2, 8, 2], x_length=7, y_length=4)
        graph = axes.plot(lambda x: x**2 - 4 * x + 3, color=BLUE)
        labels = VGroup(
            Text("y = x^2 - 4x + 3", font_size=28).to_edge(UP),
            Text("y = (x - 2)^2 - 1", font_size=24).next_to(axes, DOWN),
            Text("vertex", font_size=20).next_to(axes.c2p(2, -1), DOWN),
            Text("x-intercepts", font_size=20).next_to(axes.c2p(1, 0), UP),
            Text("y-intercept", font_size=20).next_to(axes.c2p(0, 3), LEFT),
            Text("axis of symmetry", font_size=20).next_to(axes.c2p(2, 6), RIGHT),
        )
        markers = VGroup(
            Dot(axes.c2p(2, -1), color=RED),
            Dot(axes.c2p(1, 0), color=GREEN),
            Dot(axes.c2p(3, 0), color=GREEN),
            Dot(axes.c2p(0, 3), color=YELLOW),
            DashedLine(axes.c2p(2, -1.5), axes.c2p(2, 7), color=RED),
        )
        self.play(Create(axes), Create(graph))
        self.play(FadeIn(markers), Write(labels))
        self.wait(1)
