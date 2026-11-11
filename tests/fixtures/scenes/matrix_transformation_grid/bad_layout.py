# INTENTIONALLY BAD LAYOUT. This is the same lesson as good.py, damaged on purpose
# so the layout checker has something to catch, for most of the video:
# - the title is pushed past the right edge of the frame, so it is cut off;
# - the matrix "A = [[2, 1], [0, 1]]" is drawn on top of the title, so text overlaps text;
# - the matrix is shrunk until its entries are about font size 14, and "A =" is
#   font size 12, which is too small to read.
from manim import *

I_COLOR = GREEN
J_COLOR = RED
V_COLOR = YELLOW
SQUARE_COLOR = BLUE
PANEL_X = 4.15
MATRIX = [[2, 1], [0, 1]]


class MainScene(Scene):
    def construct(self):
        origin = np.array([-5.0, -1.5, 0])
        plane = NumberPlane(
            x_range=[-12, 12, 1],
            y_range=[-8, 8, 1],
            x_length=24,
            y_length=16,
            background_line_style={"stroke_color": TEAL, "stroke_width": 2, "stroke_opacity": 0.6},
        ).shift(origin)
        ghost = NumberPlane(
            x_range=[-12, 12, 1],
            y_range=[-8, 8, 1],
            x_length=24,
            y_length=16,
            background_line_style={"stroke_color": GREY, "stroke_width": 1, "stroke_opacity": 0.35},
            axis_config={"stroke_color": GREY, "stroke_opacity": 0.5},
        ).shift(origin)

        def p(x, y):
            # Fixed screen position of the point (x, y) in the original coordinates (1 unit = 1).
            return origin + np.array([x, y, 0.0])

        # The right side is a solid panel so the moving grid never runs under the text.
        panel = Rectangle(width=6.1, height=8.2, fill_color=BLACK, fill_opacity=1, stroke_width=0)
        panel.move_to([PANEL_X + 0.05, 0, 0]).set_z_index(10)
        divider = Line([1.15, -4.1, 0], [1.15, 4.1, 0], color=GREY_B, stroke_width=2).set_z_index(10)

        def on_panel(mob):
            return mob.set_z_index(11)

        def tag(tex, color, point, direction):
            label = MathTex(tex, font_size=34, color=color)
            label.add_background_rectangle(opacity=0.85, buff=0.06)
            label.next_to(point, direction, buff=0.12)
            return label.set_z_index(4)

        title = on_panel(Text("A matrix moves the plane", font_size=34).move_to([6.3, 3.5, 0]))
        matrix = Matrix(MATRIX, h_buff=0.9, v_buff=0.7).scale(0.3)
        matrix.get_columns()[0].set_color(I_COLOR)
        matrix.get_columns()[1].set_color(J_COLOR)
        a_eq = MathTex("A =", font_size=12)
        a_group = on_panel(VGroup(a_eq, matrix).arrange(RIGHT, buff=0.05).move_to([5.2, 3.5, 0]))

        # 1. The plane and the two basis vectors.
        self.add(ghost)
        self.play(FadeIn(panel), Create(divider), Write(title), run_time=1)
        self.play(Create(plane), run_time=2)
        i_vec = Vector(p(1, 0) - origin, color=I_COLOR).shift(origin).set_z_index(3)
        j_vec = Vector(p(0, 1) - origin, color=J_COLOR).shift(origin).set_z_index(3)
        i_label = tag(r"\hat{\imath} = (1, 0)", I_COLOR, p(1, 0), DOWN)
        j_label = tag(r"\hat{\jmath} = (0, 1)", J_COLOR, p(0, 1), LEFT)
        basis_note = on_panel(Text("The basis vectors", font_size=32).move_to([PANEL_X, 1.0, 0]))
        self.play(GrowArrow(i_vec), GrowArrow(j_vec), FadeIn(basis_note), run_time=1.2)
        self.play(FadeIn(i_label), FadeIn(j_label), run_time=1)
        self.wait(0.5)

        # 2. The matrix and what its columns mean.
        self.play(Write(a_group), run_time=1.5)
        col_notes = on_panel(VGroup(
            MathTex(r"\text{column 1: where } \hat{\imath} \text{ lands}", font_size=38, color=I_COLOR),
            MathTex(r"\text{column 2: where } \hat{\jmath} \text{ lands}", font_size=38, color=J_COLOR),
        ).arrange(DOWN, buff=0.25).move_to([PANEL_X, 0.75, 0]))
        col_boxes = VGroup(
            SurroundingRectangle(matrix.get_columns()[0], color=I_COLOR, buff=0.1),
            SurroundingRectangle(matrix.get_columns()[1], color=J_COLOR, buff=0.1),
        ).set_z_index(11)
        self.play(FadeOut(basis_note), run_time=0.4)
        self.play(Create(col_boxes[0]), FadeIn(col_notes[0]), run_time=1)
        self.play(Create(col_boxes[1]), FadeIn(col_notes[1]), run_time=1)
        self.wait(1)

        # 3. One more vector, written in terms of the basis vectors.
        v_vec = Vector(p(1, 2) - origin, color=V_COLOR).shift(origin).set_z_index(3)
        v_label = tag(r"\vec{v} = (1, 2)", V_COLOR, p(1, 2), RIGHT)
        v_note = on_panel(MathTex(r"\vec{v} = \begin{bmatrix} 1 \\ 2 \end{bmatrix} = 1\,\hat{\imath} + 2\,\hat{\jmath}",
                                  font_size=40).move_to([PANEL_X, -0.75, 0]))
        self.play(GrowArrow(v_vec), FadeIn(v_label), run_time=1.2)
        self.play(Write(v_note), run_time=1.5)
        self.wait(0.8)

        # 4. The unit square.
        square = Polygon(p(0, 0), p(1, 0), p(1, 1), p(0, 1), color=SQUARE_COLOR,
                         fill_color=SQUARE_COLOR, fill_opacity=0.45, stroke_width=3).set_z_index(1)
        square_label = MathTex(r"\text{area } 1", font_size=26, color=WHITE).move_to(p(0.5, 0.5)).set_z_index(4)
        square_note = on_panel(Text("Unit square: area 1", font_size=32,
                                    color=SQUARE_COLOR).move_to([PANEL_X, -1.9, 0]))
        self.play(FadeIn(square), FadeIn(square_label), FadeIn(square_note), run_time=1.2)
        self.wait(0.8)

        # 5. Apply the matrix to the whole plane.
        go_note = on_panel(Text("Apply A to every point", font_size=34).move_to([PANEL_X, -3.1, 0]))
        self.play(FadeIn(go_note), run_time=0.6)
        ghost_v = DashedLine(origin, p(1, 2), color=V_COLOR, stroke_width=2, stroke_opacity=0.6)
        self.add(ghost_v)
        self.play(FadeOut(i_label), FadeOut(j_label), FadeOut(v_label), FadeOut(square_label), run_time=0.5)
        new_i = Vector(p(2, 0) - origin, color=I_COLOR).shift(origin).set_z_index(3)
        new_j = Vector(p(1, 1) - origin, color=J_COLOR).shift(origin).set_z_index(3)
        new_v = Vector(p(4, 2) - origin, color=V_COLOR).shift(origin).set_z_index(3)
        self.play(
            ApplyMatrix(MATRIX, plane, about_point=origin),
            ApplyMatrix(MATRIX, square, about_point=origin),
            Transform(i_vec, new_i),
            Transform(j_vec, new_j),
            Transform(v_vec, new_v),
            run_time=3.5,
        )
        self.wait(0.5)

        # 6. The basis vectors landed on the columns.
        self.play(FadeOut(VGroup(col_notes, v_note, square_note, go_note)), run_time=0.6)
        i_after = tag(r"(2, 0)", I_COLOR, p(2, 0), DOWN)
        j_after = tag(r"(1, 1)", J_COLOR, p(1, 1) + np.array([-0.15, 0.2, 0]), UL)
        land_notes = on_panel(VGroup(
            MathTex(r"\hat{\imath} \to (2, 0) = \text{column 1}", font_size=40, color=I_COLOR),
            MathTex(r"\hat{\jmath} \to (1, 1) = \text{column 2}", font_size=40, color=J_COLOR),
        ).arrange(DOWN, buff=0.25).move_to([PANEL_X, 0.75, 0]))
        self.play(FadeIn(i_after), FadeIn(land_notes[0]), Indicate(matrix.get_columns()[0], color=I_COLOR),
                  run_time=1.2)
        self.play(FadeIn(j_after), FadeIn(land_notes[1]), Indicate(matrix.get_columns()[1], color=J_COLOR),
                  run_time=1.2)
        self.wait(1)

        # 7. The other vector follows: same recipe, new basis vectors.
        v_before = tag(r"(1, 2)", V_COLOR, p(1, 2), UP)
        v_after = tag(r"(4, 2)", V_COLOR, p(4, 2), UR)
        self.play(FadeIn(v_before), FadeIn(v_after), run_time=0.8)
        hop1 = Vector(p(1, 1) - p(0, 0), color=J_COLOR).shift(p(2, 0)).set_z_index(3)
        hop2 = Vector(p(1, 1) - p(0, 0), color=J_COLOR).shift(p(3, 1)).set_z_index(3)
        arith = on_panel(VGroup(
            MathTex(r"A\vec{v} = 1\begin{bmatrix} 2 \\ 0 \end{bmatrix} + 2\begin{bmatrix} 1 \\ 1 \end{bmatrix}",
                    font_size=38),
            MathTex(r"= \begin{bmatrix} 2 \cdot 1 + 1 \cdot 2 \\ 0 \cdot 1 + 1 \cdot 2 \end{bmatrix}"
                    r" = \begin{bmatrix} 4 \\ 2 \end{bmatrix}", font_size=38),
        ).arrange(DOWN, buff=0.3, aligned_edge=LEFT).move_to([PANEL_X, -1.35, 0]))
        self.play(Write(arith[0]), run_time=1.6)
        self.play(GrowArrow(hop1), run_time=0.8)
        self.play(GrowArrow(hop2), run_time=0.8)
        self.play(Write(arith[1]), run_time=1.6)
        self.wait(1)

        # 8. The square became a parallelogram: its area is the determinant.
        self.play(FadeOut(VGroup(land_notes, arith)), FadeOut(hop1), FadeOut(hop2), FadeOut(v_before),
                  FadeOut(v_after), FadeOut(ghost_v), FadeOut(v_vec), run_time=0.8)
        base_brace = BraceBetweenPoints(p(0, 0), p(2, 0), direction=DOWN, color=WHITE)
        base_label = tag(r"\text{base } 2", WHITE, base_brace.get_bottom(), DOWN)
        height_line = DashedLine(p(3, 0), p(3, 1), color=WHITE, stroke_width=3)
        height_label = tag(r"\text{height } 1", WHITE, p(3, 0.5), RIGHT)
        area_label = MathTex(r"\text{area } 2", font_size=28, color=WHITE).move_to(p(1.5, 0.5)).set_z_index(4)
        self.play(FadeOut(i_after), FadeOut(j_after), run_time=0.4)
        self.play(GrowFromCenter(base_brace), FadeIn(base_label), run_time=1)
        self.play(Create(height_line), FadeIn(height_label), run_time=1)
        self.play(FadeIn(area_label), Indicate(square, color=SQUARE_COLOR), run_time=1.2)
        det_notes = on_panel(VGroup(
            Text("The unit square became\na parallelogram", font_size=30, color=SQUARE_COLOR, line_spacing=0.8),
            MathTex(r"\text{area} = 2 \times 1 = 2", font_size=40),
            MathTex(r"\det A = 2 \cdot 1 - 1 \cdot 0 = 2", font_size=40),
            Text("The determinant is the factor\nby which A scales every area", font_size=30,
                 line_spacing=0.8),
        ).arrange(DOWN, buff=0.35).move_to([PANEL_X, -0.55, 0]))
        self.play(FadeIn(det_notes[0]), run_time=0.8)
        self.play(Write(det_notes[1]), run_time=1.2)
        self.play(Write(det_notes[2]), run_time=1.5)
        self.play(FadeIn(det_notes[3]), run_time=1)
        self.wait(2.5)
