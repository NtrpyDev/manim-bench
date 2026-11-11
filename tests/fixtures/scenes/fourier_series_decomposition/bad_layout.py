# INTENTIONALLY BAD LAYOUT. Do not use as an example of good work.
# Same lesson as good.py, damaged on purpose so the layout checker must catch it:
# - The title is pushed past the left edge of the frame, so it is cut off, and it
#   stays on screen for the whole video.
# - A second heading sits directly on top of the title for the whole video.
# - The square wave definition, the legend and the closing statement are font
#   size 12, too small to read.
from manim import *

# Damaged copy of the known-good reference: a square wave built from odd sine harmonics.
# f(x) = (4/pi) * (sin x + sin(3x)/3 + sin(5x)/5 + ...), period 2*pi, values 1 and -1.
# The fit improves away from the jumps; a Gibbs overshoot of about 9% of the jump remains.

TERM_COLORS = {1: BLUE_C, 3: GREEN_C, 5: RED_C}
SUM_COLOR = YELLOW
X_MAX = 4 * PI


def term(k):
    return lambda x: 4 / (k * PI) * np.sin(k * x)


def partial(K):
    ks = list(range(1, K + 1, 2))
    return lambda x: 4 / PI * sum(np.sin(k * x) / k for k in ks)


class MainScene(Scene):
    def construct(self):
        title = Text("Building a square wave from sine waves", font_size=38).to_edge(UP, buff=0.3).shift(LEFT * 5.0)
        heading = Text("Fourier series of a square wave", font_size=38).move_to(title).shift(RIGHT * 0.7 + DOWN * 0.1)
        self.play(Write(title), Write(heading), run_time=1.5)

        # ---- 1. The target: a square wave on labeled axes ---------------
        axes_kw = dict(
            x_range=[0, X_MAX, PI / 2],
            y_range=[-1.5, 1.5, 0.5],
            x_length=8.0,
            tips=False,
            axis_config={"include_ticks": True, "stroke_width": 2},
            x_axis_config={"tick_size": 0.06},
            y_axis_config={"tick_size": 0.06},
        )
        bottom = Axes(y_length=2.6, **axes_kw).move_to(np.array([-2.6, -1.75, 0.0]))
        x_ticks = VGroup()
        for n, s in [(1, r"\pi"), (2, r"2\pi"), (3, r"3\pi"), (4, r"4\pi")]:
            x_ticks.add(MathTex(s, font_size=28).next_to(bottom.c2p(n * PI, -1.5), DOWN, buff=0.12))
        y_ticks = VGroup(
            MathTex("1", font_size=28).next_to(bottom.c2p(0, 1), LEFT, buff=0.12),
            MathTex("-1", font_size=28).next_to(bottom.c2p(0, -1), LEFT, buff=0.12),
        )
        x_lab = MathTex("x", font_size=32).next_to(bottom.c2p(X_MAX, 0), RIGHT, buff=0.15)
        y_lab = MathTex("y", font_size=32).next_to(bottom.c2p(0, 1.5), UP, buff=0.1)
        grid_lines = VGroup(*[
            DashedLine(bottom.c2p(n * PI, -1.5), bottom.c2p(n * PI, 1.5), stroke_width=1, color=GREY_D)
            for n in range(1, 5)
        ])

        square = VGroup()
        for n in range(4):
            level = 1 if n % 2 == 0 else -1
            square.add(Line(bottom.c2p(n * PI, level), bottom.c2p((n + 1) * PI, level), color=WHITE, stroke_width=5))
            if n > 0:
                square.add(DashedLine(bottom.c2p(n * PI, -1), bottom.c2p(n * PI, 1), color=GREY_B, stroke_width=2))

        d1 = Tex(r"Square wave $f(x)$, period $2\pi$:", font_size=12)
        d2 = Tex(r"$f(x) = 1$ for $0 < x < \pi$", font_size=12)
        d3 = Tex(r"$f(x) = -1$ for $\pi < x < 2\pi$", font_size=12)
        defs = VGroup(d1, d2, d3).arrange(DOWN, aligned_edge=LEFT, buff=0.25).move_to(np.array([4.4, -1.4, 0.0]))

        self.play(Create(bottom), FadeIn(x_ticks), FadeIn(y_ticks), FadeIn(x_lab), FadeIn(y_lab),
                  FadeIn(grid_lines), run_time=2)
        self.play(Create(square), FadeIn(d1), run_time=2)
        self.play(FadeIn(d2), FadeIn(d3), run_time=1.2)
        self.wait(1.5)

        # ---- 2. The terms, one at a time --------------------------------
        top = Axes(y_length=2.3, **axes_kw).move_to(np.array([-2.6, 1.55, 0.0]))
        top_y = VGroup(
            MathTex("1", font_size=28).next_to(top.c2p(0, 1), LEFT, buff=0.12),
            MathTex("-1", font_size=28).next_to(top.c2p(0, -1), LEFT, buff=0.12),
        )
        top_head = Tex(r"Odd harmonics $\sin(kx)$, $k = 1, 3, 5$", font_size=32).move_to(np.array([-2.6, 3.2, 0.0]))
        self.play(FadeOut(defs), run_time=0.8)
        self.play(Create(top), FadeIn(top_y), FadeIn(top_head), run_time=1.5)

        legend_sq = Tex(r"white: square wave $f(x)$", font_size=12).move_to(np.array([4.4, -2.75, 0.0]))
        legend_sum = Tex(r"yellow: running sum $S(x)$", font_size=12, color=SUM_COLOR).move_to(np.array([4.4, -0.75, 0.0]))

        term_labels = {
            1: MathTex(r"k=1:\ \frac{4}{\pi}\sin x", font_size=32, color=TERM_COLORS[1]),
            3: MathTex(r"k=3:\ \frac{4}{3\pi}\sin 3x", font_size=32, color=TERM_COLORS[3]),
            5: MathTex(r"k=5:\ \frac{4}{5\pi}\sin 5x", font_size=32, color=TERM_COLORS[5]),
        }
        for i, k in enumerate([1, 3, 5]):
            term_labels[k].move_to(np.array([4.0, 2.55 - 0.85 * i, 0.0]), aligned_edge=LEFT).shift(LEFT * 1.3)

        sum_texts = {
            1: MathTex(r"S = \frac{4}{\pi}\sin x", font_size=30),
            3: MathTex(r"S = \frac{4}{\pi}\Big(\sin x + \frac{\sin 3x}{3}\Big)", font_size=30),
            5: MathTex(r"S = \frac{4}{\pi}\Big(\sin x + \frac{\sin 3x}{3} + \frac{\sin 5x}{5}\Big)", font_size=30),
        }
        for k in sum_texts:
            sum_texts[k].move_to(np.array([4.45, -1.65, 0.0]))

        sum_curve = None
        sum_text = None
        terms = {}
        for k in [1, 3, 5]:
            curve = top.plot(term(k), x_range=[0, X_MAX, 0.01], color=TERM_COLORS[k], stroke_width=4)
            terms[k] = curve
            self.play(Create(curve), Write(term_labels[k]), run_time=2)
            new_sum = bottom.plot(partial(k), x_range=[0, X_MAX, 0.01], color=SUM_COLOR, stroke_width=4)
            moving = curve.copy()
            if sum_curve is None:
                self.play(Transform(moving, new_sum), FadeIn(legend_sum), FadeIn(legend_sq),
                          FadeIn(sum_texts[k]), run_time=2)
                self.remove(moving)
                self.add(new_sum)
            else:
                self.play(
                    ReplacementTransform(VGroup(sum_curve, moving), new_sum),
                    ReplacementTransform(sum_text, sum_texts[k]),
                    run_time=2,
                )
            sum_curve = new_sum
            sum_text = sum_texts[k]
            self.wait(1)

        # ---- 3. Many more terms -----------------------------------------
        self.play(FadeOut(sum_text), run_time=0.6)
        counter = None
        for K in [9, 19, 49]:
            new_sum = bottom.plot(partial(K), x_range=[0, X_MAX, 0.004], color=SUM_COLOR, stroke_width=2.5)
            new_counter = Tex(rf"odd $k$ up to $k = {K}$", font_size=32).move_to(np.array([4.4, -1.65, 0.0]))
            anims = [ReplacementTransform(sum_curve, new_sum)]
            anims.append(FadeIn(new_counter) if counter is None else ReplacementTransform(counter, new_counter))
            self.play(*anims, run_time=1.6)
            sum_curve = new_sum
            counter = new_counter
            self.wait(0.6)

        peak = 1.179
        over = DashedLine(bottom.c2p(0, peak), bottom.c2p(X_MAX, peak), color=ORANGE, stroke_width=2)
        over_lab = MathTex(r"1.18", font_size=26, color=ORANGE).next_to(bottom.c2p(X_MAX, peak), RIGHT, buff=0.12)
        self.play(Create(over), FadeIn(over_lab), run_time=1.2)
        self.wait(1)

        # ---- 4. The whole series and what happens -----------------------
        self.play(FadeOut(VGroup(top, top_y, top_head, *terms.values(), *term_labels.values())), run_time=1)
        series = MathTex(
            r"f(x) = \frac{4}{\pi}\sum_{k = 1, 3, 5, \dots} \frac{\sin kx}{k}"
            r" = \frac{4}{\pi}\Big(\sin x + \frac{\sin 3x}{3} + \frac{\sin 5x}{5} + \cdots\Big)",
            font_size=38,
        ).move_to(np.array([0.0, 2.85, 0.0]))
        series_head = Tex(r"The whole series (odd $k$ only):", font_size=32).next_to(series, UP, buff=0.2)
        self.play(FadeIn(series_head), Write(series), run_time=2.5)
        self.wait(1)

        b1 = Tex(r"As more terms are added, the sum gets closer to the square wave", font_size=12)
        b2 = Tex(r"everywhere away from the jumps. Next to each jump an overshoot", font_size=12)
        b3 = Tex(r"of about 9\% of the jump (peak near 1.18) remains: the Gibbs phenomenon.", font_size=12)
        behavior = VGroup(b1, b2, b3).arrange(DOWN, aligned_edge=LEFT, buff=0.18).move_to(np.array([0.0, 0.85, 0.0]))
        self.play(FadeIn(b1), run_time=1.3)
        self.play(FadeIn(b2), run_time=1.3)
        self.play(FadeIn(b3), Indicate(over, color=ORANGE), run_time=1.5)
        self.wait(3)
