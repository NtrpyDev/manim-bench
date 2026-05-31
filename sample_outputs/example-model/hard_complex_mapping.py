from manim import *


class MainScene(Scene):
    def construct(self):
        left = ComplexPlane(x_length=5, y_length=5).shift(LEFT * 3)
        right = ComplexPlane(x_length=5, y_length=5).shift(RIGHT * 3)
        title = Text("f(z) = z^2", font_size=34).to_edge(UP)
        formula = Text("z = r e^{i theta} maps to z^2 = r^2 e^{i 2 theta}", font_size=24).to_edge(DOWN)
        labels = VGroup(
            Text("domain", font_size=22).next_to(left, UP),
            Text("codomain", font_size=22).next_to(right, UP),
            Text("modulus", font_size=20).shift(LEFT * 4 + DOWN * 2.5),
            Text("argument", font_size=20).shift(LEFT * 2 + DOWN * 2.5),
            Text("doubled angle", font_size=20).shift(RIGHT * 2 + DOWN * 2.5),
            Text("squared radius", font_size=20).shift(RIGHT * 4 + DOWN * 2.5),
            Text("branch behavior", font_size=20).shift(UP * 2.3),
        )
        z = Dot(left.n2p(1 + 1j), color=YELLOW)
        z2 = Dot(right.n2p((1 + 1j) ** 2), color=GREEN)
        self.play(Write(title), Create(left), Create(right), Write(formula))
        self.play(FadeIn(z), FadeIn(z2), Write(labels))
        self.wait(1)
