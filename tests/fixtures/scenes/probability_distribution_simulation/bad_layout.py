# INTENTIONALLY BAD LAYOUT. Do not use as an example of good work.
# Same lesson as good.py, damaged on purpose so the layout checker must catch it:
# - The title is pushed past the right edge of the frame, so it is cut off, and
#   it stays on screen for the whole video.
# - A second heading sits directly on top of the title for the whole video.
# - The explanation text is font size 12, too small to read.
from manim import *

# Damaged copy of the known-good reference: the distribution of the sum X of two fair dice.
# Counts 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1 out of 36, total 36/36 = 1, E[X] = 7.

CELL = 0.62
GRID_X0 = -5.15  # center of column 1
GRID_Y0 = 1.25   # center of row 1
SUM_COLORS = color_gradient([BLUE_C, TEAL_C, GREEN_C, YELLOW_C, ORANGE, RED_C], 11)


def count(k):
    return 6 - abs(k - 7)


class MainScene(Scene):
    def construct(self):
        title = Text("The sum of two dice: where its distribution comes from", font_size=36)
        title.to_edge(UP, buff=0.3).shift(RIGHT * 3.5)
        heading = Text("Counting outcomes of two fair dice", font_size=36).move_to(title).shift(LEFT * 0.8 + DOWN * 0.1)
        self.play(Write(title), Write(heading), run_time=1.5)

        # ---- 1. All 36 outcomes ------------------------------------------
        cells = {}
        sums = {}
        for i in range(1, 7):
            for j in range(1, 7):
                pos = np.array([GRID_X0 + (j - 1) * CELL, GRID_Y0 - (i - 1) * CELL, 0.0])
                cells[(i, j)] = Square(side_length=CELL, color=GREY_B, stroke_width=2).move_to(pos)
                sums[(i, j)] = MathTex(str(i + j), font_size=30).move_to(pos)
        grid = VGroup(*cells.values())
        col_heads = VGroup(*[
            MathTex(str(j), font_size=32, color=BLUE_B).move_to(cells[(1, j)].get_center() + UP * 0.55)
            for j in range(1, 7)
        ])
        row_heads = VGroup(*[
            MathTex(str(i), font_size=32, color=RED_B).move_to(cells[(i, 1)].get_center() + LEFT * 0.55)
            for i in range(1, 7)
        ])
        die2 = Text("Die 2", font_size=28, color=BLUE_B).next_to(col_heads, UP, buff=0.2)
        die1 = Text("Die 1", font_size=28, color=RED_B).rotate(PI / 2).next_to(row_heads, LEFT, buff=0.2)

        a1 = Tex(r"Two fair dice: $6 \times 6 = 36$ outcomes,", font_size=12)
        a2 = Tex(r"all equally likely, each with probability $\tfrac{1}{36}$.", font_size=12)
        a3 = Tex(r"Each cell shows the sum $X = \text{die 1} + \text{die 2}$.", font_size=12)
        a4 = Tex(r"Equal sums line up on a diagonal.", font_size=12)
        intro = VGroup(a1, a2, a3, a4).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        intro.move_to(np.array([3.1, 1.0, 0.0]))

        self.play(Create(grid), FadeIn(col_heads), FadeIn(row_heads), FadeIn(die1), FadeIn(die2), run_time=2)
        self.play(FadeIn(a1), FadeIn(a2), run_time=1.2)
        self.play(LaggedStart(*[FadeIn(m) for m in sums.values()], lag_ratio=0.06), FadeIn(a3), run_time=3)
        self.wait(0.5)

        # Show one diagonal of equal sums.
        seven = [(i, 7 - i) for i in range(1, 7)]
        marks = VGroup(*[
            Square(side_length=CELL * 0.92, color=YELLOW, stroke_width=5).move_to(cells[c]) for c in seven
        ])
        self.play(FadeIn(a4), Create(marks), run_time=1.5)
        self.wait(1)

        # ---- 2. One probability worked out -------------------------------
        self.play(FadeOut(VGroup(a1, a2, a3, a4)), run_time=0.8)
        b1 = Tex(r"$X = 7$ happens in 6 outcomes:", font_size=12)
        b2 = MathTex(r"(1,6),\ (2,5),\ (3,4),\ (4,3),\ (5,2),\ (6,1)", font_size=12)
        b3 = MathTex(r"P(X = 7) = \frac{6}{36} = \frac{1}{6}", font_size=44, color=YELLOW)
        work = VGroup(b1, b2, b3).arrange(DOWN, aligned_edge=LEFT, buff=0.4).move_to(np.array([3.0, 0.8, 0.0]))
        self.play(FadeIn(b1), Indicate(marks, color=YELLOW), run_time=1.5)
        self.play(Write(b2), run_time=2)
        self.play(Write(b3), run_time=1.5)
        self.wait(2)

        # ---- 3. The bar chart, one sum at a time -------------------------
        self.play(FadeOut(VGroup(b1, b2, b3, marks)), run_time=1)
        axes = Axes(
            x_range=[1, 13, 1],
            y_range=[0, 7, 1],
            x_length=6.0,
            y_length=4.4,
            tips=False,
            axis_config={"include_ticks": True, "stroke_width": 3},
        ).move_to(np.array([3.95, 0.25, 0.0]))
        x_nums = VGroup(*[
            MathTex(str(k), font_size=26).next_to(axes.c2p(k, 0), DOWN, buff=0.18) for k in range(2, 13)
        ])
        y_nums = VGroup(*[
            MathTex(rf"{n}/36", font_size=26).next_to(axes.c2p(1, n), LEFT, buff=0.15)
            for n in range(1, 7)
        ])
        x_label = Tex(r"$k$ = sum of the two dice", font_size=30).next_to(x_nums, DOWN, buff=0.2)
        y_label = MathTex(r"P(X = k)", font_size=12).next_to(axes.c2p(1, 7), UP, buff=0.2)
        self.play(Create(axes), FadeIn(x_nums), FadeIn(y_nums), FadeIn(x_label), FadeIn(y_label), run_time=2)

        step_text = None
        bars = {}
        for k in range(2, 13):
            n = count(k)
            color = SUM_COLORS[k - 2]
            bar = Rectangle(
                width=0.38, height=axes.c2p(0, n)[1] - axes.c2p(0, 0)[1],
                fill_color=color, fill_opacity=0.85, stroke_color=WHITE, stroke_width=1.5,
            )
            bar.move_to(axes.c2p(k, 0), aligned_edge=DOWN)
            bars[k] = bar
            diag = [(i, k - i) for i in range(1, 7) if 1 <= k - i <= 6]
            new_text = MathTex(
                rf"X = {k}:\ {n} \text{{ outcome{'s' if n > 1 else ''}}},\quad P(X = {k}) = \frac{{{n}}}{{36}}",
                font_size=34,
            ).move_to(np.array([0.0, -3.45, 0.0]))
            anims = [cells[c].animate.set_fill(color, opacity=0.6) for c in diag]
            anims.append(GrowFromEdge(bar, DOWN))
            if step_text is None:
                anims.append(FadeIn(new_text))
            else:
                anims.append(FadeOut(step_text))
                anims.append(FadeIn(new_text))
            self.play(*anims, run_time=0.9)
            step_text = new_text
        self.wait(1)

        # ---- 4. The probabilities add up to 1 ----------------------------
        left_side = VGroup(grid, *sums.values(), col_heads, row_heads, die1, die2)
        self.play(FadeOut(left_side), FadeOut(step_text), run_time=1)
        c1 = Tex(r"Check: the probabilities add up to 1", font_size=12)
        c2 = MathTex(r"\frac{1+2+3+4+5+6+5+4+3+2+1}{36} = \frac{36}{36} = 1", font_size=28)
        check = VGroup(c1, c2).arrange(DOWN, aligned_edge=LEFT, buff=0.3).move_to(np.array([-3.55, 2.65, 0.0]))
        self.play(FadeIn(c1), run_time=1)
        self.play(Write(c2), run_time=2)
        self.wait(1.5)

        # ---- 5. Expected value -------------------------------------------
        e0 = Tex(r"Expected value: weight each $k$ by $P(X = k)$", font_size=12)
        e1 = MathTex(r"E[X] = \sum_{k=2}^{12} k\, P(X = k)", font_size=12)
        e2 = MathTex(r"= \tfrac{1}{36}\big(2\cdot1 + 3\cdot2 + 4\cdot3 + 5\cdot4 + 6\cdot5", font_size=30)
        e3 = MathTex(r"+\, 7\cdot6 + 8\cdot5 + 9\cdot4 + 10\cdot3 + 11\cdot2 + 12\cdot1\big)", font_size=30)
        e4 = MathTex(r"= \frac{252}{36} = 7", font_size=40, color=YELLOW)
        ev = VGroup(e0, e1, e2, e3, e4).arrange(DOWN, aligned_edge=LEFT, buff=0.28)
        ev.move_to(np.array([-3.55, -0.85, 0.0]))
        e3.shift(RIGHT * 0.35)
        self.play(FadeIn(e0), run_time=1)
        self.play(Write(e1), run_time=1.5)
        self.play(Write(e2), run_time=1.8)
        self.play(Write(e3), run_time=1.8)
        self.play(Write(e4), run_time=1.2)

        ev_line = DashedLine(axes.c2p(7, 0), axes.c2p(7, 7), color=YELLOW, stroke_width=4)
        ev_label = MathTex(r"E[X] = 7", font_size=12, color=YELLOW).next_to(axes.c2p(7, 7), UP, buff=0.2)
        self.play(Create(ev_line), FadeIn(ev_label), run_time=1.5)
        sym = Tex(r"The chart is symmetric about 7, its balance point.", font_size=12)
        sym.move_to(np.array([0.0, -3.55, 0.0]))
        self.play(FadeIn(sym), Indicate(bars[7], color=YELLOW), run_time=1.5)
        self.wait(3)
