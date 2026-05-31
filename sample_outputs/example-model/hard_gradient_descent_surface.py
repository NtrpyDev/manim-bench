from manim import *


class MainScene(Scene):
    def construct(self):
        axes = Axes(x_range=[-4, 4, 1], y_range=[0, 18, 4], x_length=7, y_length=4)
        curve = axes.plot(lambda x: x**2, color=BLUE)
        points = [axes.c2p(x, x**2) for x in [3, 2.2, 1.5, 0.9, 0.35, 0]]
        path = VMobject(color=GREEN).set_points_as_corners(points)
        dots = VGroup(*[Dot(point, color=YELLOW) for point in points])
        labels = VGroup(
            Text("f(x, y) = x^2 + 2y^2", font_size=30).to_edge(UP),
            Text("gradient", font_size=20).shift(LEFT * 3 + UP),
            Text("negative gradient", font_size=20).shift(LEFT * 2 + DOWN * 2.4),
            Text("learning rate", font_size=20).shift(RIGHT * 1.5 + DOWN * 2.4),
            Text("update rule", font_size=20).to_edge(DOWN),
            Text("minimum", font_size=20).next_to(points[-1], RIGHT),
            Text("iterate", font_size=20).next_to(points[1], UP),
        )
        self.play(Create(axes), Create(curve), Write(labels[0]))
        self.play(Create(path), FadeIn(dots), Write(labels[1:]))
        self.wait(1)
