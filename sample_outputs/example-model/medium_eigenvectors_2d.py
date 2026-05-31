from manim import *


class MainScene(Scene):
    def construct(self):
        plane = NumberPlane()
        title = Text("A = [[2, 1], [1, 2]]", font_size=32).to_edge(UP)
        formula = Text("Av = lambda v", font_size=28).to_edge(DOWN)
        v1 = Vector([2, 1], color=BLUE)
        v2 = Vector([-1, 2], color=YELLOW)
        e1 = Vector([2, 2], color=GREEN)
        e2 = Vector([2, -2], color=RED)
        labels = VGroup(
            Text("input vector", font_size=20).next_to(v1, RIGHT),
            Text("transformed vector", font_size=20).next_to(v2, LEFT),
            Text("eigenvector", font_size=20).next_to(e1, RIGHT),
            Text("eigenvalue 3", font_size=20).next_to(e1, UP),
            Text("eigenvalue 1", font_size=20).next_to(e2, DOWN),
        )
        self.play(Create(plane), Write(title), Write(formula))
        self.play(GrowArrow(v1), GrowArrow(v2))
        self.play(GrowArrow(e1), GrowArrow(e2), Write(labels))
        self.wait(1)
