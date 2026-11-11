from manim import *

CURVE_COLOR = BLUE
SECANT_COLOR = YELLOW
TANGENT_COLOR = GREEN
RUN_COLOR = ORANGE
RISE_COLOR = PINK

X_MIN, X_MAX = -2.5, 2.5
Y_MIN, Y_MAX = -1.0, 6.0
PANEL_X = 3.8


def f(x):
    return x * x


class MainScene(Scene):
    def construct(self):
        axes = Axes(
            x_range=[X_MIN, X_MAX, 1],
            y_range=[Y_MIN, Y_MAX, 1],
            x_length=6.3,
            y_length=6.2,
            tips=True,
            axis_config={"font_size": 26},
            x_axis_config={"numbers_to_include": [-2, -1, 1, 2]},
            y_axis_config={"numbers_to_include": [1, 2, 3, 4, 5]},
        ).move_to([-3.35, -0.45, 0])
        tick_numbers = VGroup(axes.x_axis.numbers, axes.y_axis.numbers)
        tick_numbers.set_stroke(BLACK, width=6, background=True)
        tick_numbers.set_z_index(5)
        x_label = MathTex("x", font_size=34).next_to(axes.x_axis.get_right(), DOWN, buff=0.2)
        y_label = MathTex("y", font_size=34).next_to(axes.y_axis.get_top(), LEFT, buff=0.2)
        graph = axes.plot(f, x_range=[-2.4, 2.4], color=CURVE_COLOR, stroke_width=4)
        graph_label = MathTex("f(x) = x^2", font_size=36, color=CURVE_COLOR).move_to(axes.c2p(-1.2, 5.5))

        title = Text("The derivative as a slope", font_size=36).move_to([PANEL_X, 3.5, 0])

        def clipped_line(x0, y0, slope, color, width=4):
            """The line through (x0, y0) with this slope, cut to the visible part of the axes."""
            lo, hi = X_MIN + 0.1, X_MAX - 0.1
            if abs(slope) > 1e-9:
                xa = x0 + (Y_MIN + 0.05 - y0) / slope
                xb = x0 + (Y_MAX - 0.3 - y0) / slope
                lo = max(lo, min(xa, xb))
                hi = min(hi, max(xa, xb))
            return Line(axes.c2p(lo, y0 + slope * (lo - x0)), axes.c2p(hi, y0 + slope * (hi - x0)),
                        color=color, stroke_width=width)

        # 1. The curve.
        self.play(Write(title), run_time=1.5)
        self.play(Create(axes), Write(x_label), Write(y_label), run_time=2)
        self.play(Create(graph), Write(graph_label), run_time=2)
        self.wait(0.5)

        # 2. Two points and the line through them.
        a = 1.0
        h = ValueTracker(1.0)
        p_dot = Dot(axes.c2p(a, f(a)), color=WHITE, radius=0.08).set_z_index(3)
        p_label = MathTex("P", font_size=34).next_to(p_dot, UL, buff=0.1)
        q_dot = always_redraw(lambda: Dot(axes.c2p(a + h.get_value(), f(a + h.get_value())),
                                          color=SECANT_COLOR, radius=0.08).set_z_index(3))
        q_label = MathTex("Q", font_size=34, color=SECANT_COLOR).next_to(axes.c2p(2, 4), DR, buff=0.1)
        secant = always_redraw(lambda: clipped_line(a, f(a), 2 * a + h.get_value(), SECANT_COLOR))

        step1 = Text("Two points on the curve", font_size=28).move_to([PANEL_X, 2.75, 0])
        coords = MathTex(r"P = (1,\ 1)", r"\qquad", r"Q = (1 + h,\ (1 + h)^2)", font_size=34)
        coords[2].set_color(SECANT_COLOR)
        coords.move_to([PANEL_X, 2.05, 0])
        self.play(FadeIn(p_dot), Write(p_label), FadeIn(step1), run_time=1)
        self.play(FadeIn(q_dot), Write(q_label), Write(coords), run_time=1.5)
        self.play(Create(secant), run_time=1)
        self.wait(0.5)

        # Rise over run with h = 1.
        run_line = Line(axes.c2p(1, 1), axes.c2p(2, 1), color=RUN_COLOR, stroke_width=5)
        rise_line = Line(axes.c2p(2, 1), axes.c2p(2, 4), color=RISE_COLOR, stroke_width=5)
        run_label = MathTex("h", font_size=34, color=RUN_COLOR).next_to(run_line, DOWN, buff=0.12)
        rise_label = MathTex(r"(1+h)^2 - 1", font_size=30, color=RISE_COLOR).next_to(rise_line, RIGHT, buff=0.12)
        rise_label.shift(DOWN * 0.4)
        slope_lines = VGroup(
            MathTex(r"\text{slope} = \frac{\text{rise}}{\text{run}}", r"= \frac{(1+h)^2 - 1}{h}", font_size=36),
            MathTex(r"= \frac{2h + h^2}{h}", r"= 2 + h", font_size=36),
        ).arrange(DOWN, buff=0.3, aligned_edge=LEFT).move_to([PANEL_X, 0.55, 0])
        slope_lines[1][1].set_color(SECANT_COLOR)
        self.play(Create(run_line), Write(run_label), run_time=1)
        self.play(Create(rise_line), Write(rise_label), run_time=1)
        self.play(Write(slope_lines[0]), run_time=2)
        self.play(Write(slope_lines[1]), run_time=2)
        example = MathTex(r"h = 1:\ \ \frac{4 - 1}{1} = 3", font_size=34).move_to([PANEL_X, -0.75, 0])
        self.play(Write(example), run_time=1.2)
        self.wait(1)

        # 3. Bring Q toward P while the slope updates.
        self.play(FadeOut(run_line), FadeOut(rise_line), FadeOut(run_label), FadeOut(rise_label),
                  FadeOut(example), FadeOut(q_label), run_time=0.8)
        h_text = MathTex("h =", font_size=40, color=RUN_COLOR)
        h_num = DecimalNumber(1.0, num_decimal_places=3, font_size=40, color=RUN_COLOR)
        s_text = MathTex(r"\text{slope} =", font_size=40, color=SECANT_COLOR)
        s_num = DecimalNumber(3.0, num_decimal_places=3, font_size=40, color=SECANT_COLOR)
        h_text.move_to([1.55, -0.8, 0])
        h_num.next_to(h_text, RIGHT, buff=0.2)
        s_text.move_to([4.5, -0.8, 0])
        s_num.next_to(s_text, RIGHT, buff=0.2)
        h_num.add_updater(lambda m: m.set_value(h.get_value()))
        s_num.add_updater(lambda m: m.set_value(2 * a + h.get_value()))
        self.play(Write(h_text), FadeIn(h_num), Write(s_text), FadeIn(s_num), run_time=1)

        table_rows = VGroup()
        anchor_top = -1.45
        for index, (value, slope_text) in enumerate([(0.5, "2.5"), (0.1, "2.1"), (0.01, "2.01"), (0.001, "2.001")]):
            self.play(h.animate.set_value(value), run_time=2.2, rate_func=smooth)
            row = MathTex(r"h = " + f"{value:g}", r"\ \Rightarrow\ ", r"\text{slope} = " + slope_text, font_size=32)
            row[0].set_color(RUN_COLOR)
            row[2].set_color(SECANT_COLOR)
            row.move_to([PANEL_X, anchor_top - 0.5 * index, 0])
            table_rows.add(row)
            self.play(FadeIn(row, shift=LEFT * 0.3), run_time=0.7)
            self.wait(0.4)

        # 4. The slope settles on 2: the tangent line.
        settle = Text("The slope settles on 2", font_size=30, color=TANGENT_COLOR).move_to([PANEL_X, -3.55, 0])
        self.play(Write(settle), run_time=1)
        tangent = clipped_line(a, f(a), 2 * a, TANGENT_COLOR, width=5)
        tangent_label = Text("tangent\nslope 2", font_size=26, color=TANGENT_COLOR, line_spacing=0.7)
        tangent_label.move_to(axes.c2p(1.95, 0.95))
        self.play(FadeOut(secant), FadeOut(q_dot), Create(tangent), run_time=1.2)
        self.play(Write(tangent_label), run_time=1)
        self.wait(1)

        # 5. The limit definition and the general result.
        h_num.clear_updaters()
        s_num.clear_updaters()
        old_panel = VGroup(step1, coords, slope_lines, h_text, h_num, s_text, s_num, table_rows, settle)
        self.play(FadeOut(old_panel), run_time=0.8)
        def_title = Text("Definition of the derivative", font_size=28).move_to([PANEL_X, 2.65, 0])
        definition = MathTex(r"f'(a) = \lim_{h \to 0} \frac{f(a + h) - f(a)}{h}", font_size=40)
        definition.move_to([PANEL_X, 1.65, 0])
        def_box = SurroundingRectangle(definition, color=WHITE, buff=0.15, corner_radius=0.1)
        self.play(FadeIn(def_title), run_time=0.6)
        self.play(Write(definition), Create(def_box), run_time=2)
        self.wait(0.8)

        general_title = MathTex(r"\text{For } f(x) = x^2:", font_size=34).move_to([PANEL_X, 0.4, 0])
        general_1 = MathTex(r"\frac{(a + h)^2 - a^2}{h}", r"= \frac{2ah + h^2}{h}", font_size=36)
        general_2 = MathTex(r"= 2a + h", r"\ \to\ 2a", r"\text{ as } h \to 0", font_size=36)
        general_1.move_to([PANEL_X, -0.55, 0])
        general_2.move_to([PANEL_X, -1.5, 0])
        self.play(Write(general_title), run_time=0.8)
        self.play(Write(general_1), run_time=1.5)
        self.play(Write(general_2), run_time=1.5)
        result = MathTex(r"f'(x) = 2x", font_size=46, color=TANGENT_COLOR).move_to([PANEL_X, -2.55, 0])
        result_box = SurroundingRectangle(result, color=TANGENT_COLOR, buff=0.15)
        self.play(Write(result), Create(result_box), run_time=1.2)
        at_one = MathTex(r"x = 1:\ 2 \cdot 1 = 2", font_size=30, color=TANGENT_COLOR).move_to([PANEL_X, -3.5, 0])
        self.play(FadeIn(at_one), Indicate(tangent_label), run_time=1.2)
        self.wait(1)

        # 6. Check the result at a second point, x = -1.
        self.play(FadeOut(VGroup(def_title, definition, def_box, general_title, general_1, general_2, at_one)),
                  result.animate.move_to([PANEL_X, 2.6, 0]), result_box.animate.move_to([PANEL_X, 2.6, 0]),
                  run_time=1)
        b = -1.0
        r_dot = Dot(axes.c2p(b, f(b)), color=WHITE, radius=0.08).set_z_index(3)
        r_label = MathTex("R", font_size=34).next_to(r_dot, LEFT, buff=0.15)
        check_title = Text("Check at a second point, x = -1", font_size=28).move_to([PANEL_X, 1.55, 0])
        predict = MathTex(r"f'(-1) = 2 \cdot (-1) = -2", font_size=38).move_to([PANEL_X, 0.6, 0])
        self.play(FadeIn(r_dot), Write(r_label), FadeIn(check_title), run_time=1)
        self.play(Write(predict), run_time=1.5)

        tangent_r = clipped_line(b, f(b), 2 * b, TANGENT_COLOR, width=5)
        run_r = Line(axes.c2p(-1, 1), axes.c2p(-0.5, 1), color=RUN_COLOR, stroke_width=5)
        rise_r = Line(axes.c2p(-0.5, 1), axes.c2p(-0.5, 0), color=RISE_COLOR, stroke_width=5)
        run_r_label = MathTex("0.5", font_size=28, color=RUN_COLOR).next_to(run_r, UP, buff=0.1)
        rise_r_label = MathTex("-1", font_size=28, color=RISE_COLOR).next_to(rise_r, RIGHT, buff=0.1)
        tangent_r_label = Text("tangent\nslope -2", font_size=26, color=TANGENT_COLOR, line_spacing=0.7)
        tangent_r_label.move_to(axes.c2p(-0.95, 3.3))
        self.play(Create(tangent_r), run_time=1.2)
        self.play(Create(run_r), Write(run_r_label), run_time=0.8)
        self.play(Create(rise_r), Write(rise_r_label), run_time=0.8)
        measured = MathTex(r"\text{tangent at } R:\ \frac{\text{rise}}{\text{run}} = \frac{-1}{0.5} = -2",
                           font_size=36).move_to([PANEL_X, -0.6, 0])
        self.play(Write(measured), FadeIn(tangent_r_label), run_time=1.5)
        agree = Text("The formula and the picture agree", font_size=28,
                     color=TANGENT_COLOR).move_to([PANEL_X, -1.75, 0])
        self.play(FadeIn(agree), Indicate(result), run_time=1.2)
        self.wait(2)
