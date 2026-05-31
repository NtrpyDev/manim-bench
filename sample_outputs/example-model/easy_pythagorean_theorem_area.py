from manim import *


class MainScene(Scene):
    def construct(self):
        title = Text("Pythagorean theorem: a^2 + b^2 = c^2", font_size=36).to_edge(UP)
        triangle = Polygon(LEFT * 2 + DOWN, RIGHT + DOWN, LEFT * 2 + UP, color=BLUE)
        right_angle = Square(0.25, color=WHITE).move_to(LEFT * 1.85 + DOWN * 0.85)
        labels = VGroup(
            Text("a", font_size=28).next_to(triangle, LEFT),
            Text("b", font_size=28).next_to(triangle, DOWN),
            Text("c", font_size=28).next_to(triangle, RIGHT),
            Text("right angle", font_size=20).next_to(right_angle, UP),
            Text("a^2", font_size=24).shift(LEFT * 3 + UP * 2),
            Text("b^2", font_size=24).shift(RIGHT * 1.8 + DOWN * 1.7),
            Text("c^2", font_size=24).shift(RIGHT * 2 + UP),
        )
        squares = VGroup(
            Square(1.0, color=GREEN).shift(LEFT * 3 + UP * 2),
            Square(1.3, color=YELLOW).shift(RIGHT * 1.8 + DOWN * 1.7),
            Square(1.65, color=RED).shift(RIGHT * 2 + UP),
        )
        self.play(Write(title))
        self.play(Create(triangle), Create(right_angle), Create(squares), Write(labels))
        self.wait(1)
