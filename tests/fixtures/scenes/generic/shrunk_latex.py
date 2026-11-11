from manim import *


class MainScene(Scene):
    def construct(self):
        # The font size Manim reports for this label is 20, but \tiny draws it far smaller.
        # The small-text check has to see the drawn size, not the reported one.
        note = Tex(r"{\tiny this caption is too small to read}", font_size=20).to_edge(DOWN)
        dot = Dot(LEFT * 4)
        self.add(Text("Shrunk inside LaTeX").scale(0.8).to_edge(UP), note, dot)
        self.play(dot.animate.shift(RIGHT * 8), run_time=16, rate_func=linear)
