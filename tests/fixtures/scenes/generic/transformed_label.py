from manim import *


class MainScene(Scene):
    def construct(self):
        # Transform keeps the first object in the scene and reshapes it into the second.
        # Manim then reports the first object's words and a nonsense font size for it.
        # The record must show the words now on screen, and must not call them small.
        label = MathTex(r"S_1(x)=\frac{4}{\pi}\sin x", font_size=40).shift(UP)
        later = Tex("terms up to k = 31", font_size=32).shift(UP)
        dot = Dot(LEFT * 4 + DOWN * 2)
        self.add(label, dot)
        self.wait(1)
        self.play(Transform(label, later), run_time=1)
        self.play(dot.animate.shift(RIGHT * 8), run_time=14, rate_func=linear)
