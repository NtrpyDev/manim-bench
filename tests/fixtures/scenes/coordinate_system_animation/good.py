from manim import *

X_COLOR = BLUE
Y_COLOR = GREEN
POINT_COLOR = YELLOW


def f(x):
    return x * x / 2 - 1


class MainScene(Scene):
    def construct(self):
        # Left half: the coordinate plane. Right half: equation, readout, checks.
        axes = Axes(
            x_range=[-3.5, 3.5, 1],
            y_range=[-1.5, 4, 1],
            x_length=7.0,
            y_length=5.5,
            tips=True,
            axis_config={"font_size": 28},
            x_axis_config={"numbers_to_include": [-3, -2, -1, 1, 2, 3]},
            y_axis_config={"numbers_to_include": [-1, 1, 2, 3]},
        ).move_to([-3.1, -0.55, 0])
        x_label = MathTex("x", font_size=36).next_to(axes.x_axis.get_right(), DOWN, buff=0.2)
        y_label = MathTex("y", font_size=36).next_to(axes.y_axis.get_top(), LEFT, buff=0.2)
        origin_dot = Dot(axes.c2p(0, 0), radius=0.06, color=WHITE)
        origin_label = MathTex("O", font_size=28).next_to(origin_dot, UR, buff=0.08)

        title = Text("A graph is made of points", font_size=36).move_to([3.75, 3.4, 0])

        self.play(Write(title), run_time=1.5)
        # Tick numbers get a dark outline and sit in front, so the curve passes behind them.
        tick_numbers = VGroup(axes.x_axis.numbers, axes.y_axis.numbers)
        tick_numbers.set_stroke(BLACK, width=6, background=True)
        tick_numbers.set_z_index(5)
        self.play(Create(axes), run_time=2.5)
        self.play(Write(x_label), Write(y_label), run_time=1)
        self.play(FadeIn(origin_dot), Write(origin_label), run_time=1)
        origin_note = Text("O is the origin (0, 0)", font_size=26).move_to([3.75, -2.6, 0])
        self.play(FadeIn(origin_note), run_time=1)
        self.wait(1)

        # The rule that decides which points belong to the graph.
        equation = MathTex(r"y", r"=", r"\frac{x^2}{2} - 1", font_size=52).move_to([3.75, 2.35, 0])
        equation[0].set_color(Y_COLOR)
        eq_box = SurroundingRectangle(equation, color=WHITE, buff=0.18, corner_radius=0.1)
        rule_note = Text("A point (x, y) is on the graph\nwhen its y equals this rule", font_size=26,
                         line_spacing=0.8).move_to([3.75, -2.6, 0])
        self.play(FadeOut(origin_note), run_time=0.5)
        self.play(Write(equation), Create(eq_box), run_time=1.5)
        self.play(FadeIn(rule_note), run_time=1)
        self.wait(1.5)

        # The moving point, its guide lines to the axes, and the live readout.
        t = ValueTracker(-3.0)

        def point_at():
            x = t.get_value()
            return axes.c2p(x, f(x))

        dot = always_redraw(lambda: Dot(point_at(), radius=0.09, color=POINT_COLOR))

        def guide(to_x_axis):
            x = t.get_value()
            start = point_at()
            end = axes.c2p(x, 0) if to_x_axis else axes.c2p(0, f(x))
            if np.linalg.norm(end - start) < 0.05:
                return VMobject()
            color = X_COLOR if to_x_axis else Y_COLOR
            return DashedLine(start, end, color=color, stroke_width=3, dash_length=0.1)

        x_guide = always_redraw(lambda: guide(True))
        y_guide = always_redraw(lambda: guide(False))
        x_foot = always_redraw(lambda: Dot(axes.c2p(t.get_value(), 0), radius=0.06, color=X_COLOR))
        y_foot = always_redraw(lambda: Dot(axes.c2p(0, f(t.get_value())), radius=0.06, color=Y_COLOR))

        x_text = MathTex("x", "=", font_size=44)
        x_text[0].set_color(X_COLOR)
        x_num = DecimalNumber(-3.0, num_decimal_places=2, include_sign=True, font_size=44, color=X_COLOR)
        y_text = MathTex("y", "=", font_size=44)
        y_text[0].set_color(Y_COLOR)
        y_num = DecimalNumber(f(-3.0), num_decimal_places=2, include_sign=True, font_size=44, color=Y_COLOR)
        x_text.move_to([2.6, 0.5, 0])
        y_text.move_to([2.6, -0.25, 0])
        x_num.next_to(x_text, RIGHT, buff=0.25)
        y_num.next_to(y_text, RIGHT, buff=0.25)
        x_num.add_updater(lambda m: m.set_value(t.get_value()).next_to(x_text, RIGHT, buff=0.25))
        y_num.add_updater(lambda m: m.set_value(f(t.get_value())).next_to(y_text, RIGHT, buff=0.25))
        readout_title = Text("Point's coordinates", font_size=26, color=POINT_COLOR).move_to([3.75, 1.1, 0])
        readout_title.align_to(x_text, LEFT)

        trace = TracedPath(lambda: point_at(), stroke_color=POINT_COLOR, stroke_width=5)

        start_note = Text("Start at x = -3", font_size=26).move_to([3.75, -2.6, 0])
        self.play(FadeOut(rule_note), run_time=0.5)
        self.play(FadeIn(dot, scale=0.5), FadeIn(start_note), run_time=1)
        self.play(Create(x_guide), Create(y_guide), FadeIn(x_foot), FadeIn(y_foot), run_time=1)
        self.play(FadeIn(readout_title), Write(x_text), Write(y_text), FadeIn(x_num), FadeIn(y_num), run_time=1.5)
        self.add(trace)
        self.wait(1)

        move_note = Text("The point moves and leaves\nthe graph behind it", font_size=26,
                         line_spacing=0.8).move_to([3.75, -2.6, 0])
        self.play(FadeOut(start_note), FadeIn(move_note), run_time=0.8)

        def check_stop(number, x_tex, square_tex, result_tex):
            """Put the point's x into the rule and show the result equals its y."""
            block = VGroup(
                Text(f"Check {number} of 3: x = {x_tex}", font_size=28, color=X_COLOR),
                MathTex(r"y = \frac{(" + x_tex + r")^2}{2} - 1", r"= " + square_tex + r" - 1 = " + result_tex,
                        font_size=38),
                Text("matches the point's y  ✓", font_size=26, color=Y_COLOR),
            ).arrange(DOWN, buff=0.28)
            block.move_to([3.75, 0, 0]).align_to(np.array([0, -0.8, 0]), UP)
            ring = Circle(radius=0.22, color=POINT_COLOR, stroke_width=4).move_to(point_at())
            return block, ring

        stops = [
            (-2.0, "-2", r"\frac{4}{2}", "1"),
            (0.0, "0", r"\frac{0}{2}", "-1"),
            (2.0, "2", r"\frac{4}{2}", "1"),
        ]
        current_note = move_note
        for number, (x_value, x_tex, square_tex, result_tex) in enumerate(stops, start=1):
            self.play(t.animate.set_value(x_value), run_time=3, rate_func=smooth)
            block, ring = check_stop(number, x_tex, square_tex, result_tex)
            heading, formula, verdict = block
            self.play(FadeOut(current_note), Create(ring), FadeIn(heading), run_time=0.8)
            self.play(Write(formula[0]), run_time=1.2)
            self.play(Write(formula[1]), run_time=1.2)
            self.play(FadeIn(verdict), Indicate(y_num, color=WHITE), run_time=1.2)
            self.wait(1.2)
            current_note = block
            self.play(FadeOut(ring), run_time=0.4)

        end_move_note = Text("Keep going to x = 3", font_size=26).move_to([3.75, -2.6, 0])
        self.play(FadeOut(current_note), FadeIn(end_move_note), run_time=0.8)
        self.play(t.animate.set_value(3.0), run_time=2.5, rate_func=smooth)
        self.wait(0.5)

        # Freeze the readout and state the conclusion.
        x_num.clear_updaters()
        y_num.clear_updaters()
        curve_label = MathTex(r"y = \frac{x^2}{2} - 1", font_size=34, color=POINT_COLOR)
        curve_label.move_to(axes.c2p(-1.4, 2.6))
        summary = Text("Every point on the curve has\ncoordinates that satisfy the rule", font_size=26,
                       line_spacing=0.8).move_to([3.75, -2.25, 0])
        lowest = Text("Lowest point (0, -1)", font_size=24)
        lowest.move_to(axes.c2p(0, -1.3)).align_to(axes.c2p(0.3, 0), LEFT)
        self.play(FadeOut(end_move_note), Write(curve_label), run_time=1.2)
        self.play(FadeIn(summary), run_time=1)
        self.play(FadeIn(lowest), Flash(axes.c2p(0, -1), color=POINT_COLOR), run_time=1)
        self.play(Indicate(equation), run_time=1.2)
        self.wait(2)
