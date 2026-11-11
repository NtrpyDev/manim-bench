from manim import *

# Known-good reference: the Pythagorean theorem by rearrangement.
# Legs a and b, hypotenuse c. Four copies of the triangle sit inside a square
# of side a + b in two ways; the uncovered area is the same both times.

A = 1.6
B = 2.6
S = A + B
ORIGIN_PT = np.array([-6.0, -2.4, 0.0])  # lower-left corner of the big square

TRI_COLOR = BLUE_D
C_COLOR = YELLOW
A_COLOR = GREEN
B_COLOR = RED


def P(x, y, origin=ORIGIN_PT, scale=1.0):
    return origin + scale * np.array([x, y, 0.0])


def triangle(points):
    return Polygon(
        *points, color=WHITE, stroke_width=3, fill_color=TRI_COLOR, fill_opacity=0.75
    )


class MainScene(Scene):
    def construct(self):
        title = Text("The Pythagorean theorem by rearrangement", font_size=40)
        title.to_edge(UP, buff=0.35)
        self.play(Write(title), run_time=1.5)
        self.wait(0.5)

        # ---- 1. One right triangle -------------------------------------
        k = 1.25
        o = np.array([-5.6, -2.2, 0.0])
        q0, q1, q2 = o, o + k * A * RIGHT, o + k * B * UP
        tri = triangle([q0, q1, q2])
        leg_a = Line(q0, q1)
        leg_b = Line(q0, q2)
        hyp = Line(q1, q2)
        lab_a = MathTex("a", font_size=44, color=A_COLOR).next_to(leg_a, DOWN, buff=0.15)
        lab_b = MathTex("b", font_size=44, color=B_COLOR).next_to(leg_b, LEFT, buff=0.15)
        lab_c = MathTex("c", font_size=44, color=C_COLOR).move_to(
            hyp.get_center() + 0.35 * normalize(np.array([B, A, 0.0]))
        )
        right_mark = RightAngle(leg_a, leg_b, length=0.3, color=WHITE)
        ang_alpha = Angle(Line(q1, q2), Line(q1, q0), radius=0.55, color=ORANGE)
        ang_beta = Angle(Line(q2, q0), Line(q2, q1), radius=0.55, color=PURPLE_A)
        lab_alpha = MathTex(r"\alpha", font_size=34, color=ORANGE).move_to(
            Angle(Line(q1, q2), Line(q1, q0), radius=0.85).point_from_proportion(0.5)
        )
        lab_beta = MathTex(r"\beta", font_size=34, color=PURPLE_A).move_to(
            Angle(Line(q2, q0), Line(q2, q1), radius=0.9).point_from_proportion(0.5)
        )

        info1 = Tex(r"A right triangle with legs $a$, $b$", font_size=36)
        info2 = Tex(r"and hypotenuse $c$.", font_size=36)
        info3 = Tex(r"The right angle is marked.", font_size=36)
        info4 = Tex(r"Its acute angles: $\alpha + \beta = 90^\circ$", font_size=36)
        info = VGroup(info1, info2, info3, info4).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        info.move_to(np.array([2.6, 0.6, 0.0]))

        self.play(DrawBorderThenFill(tri), run_time=1.5)
        self.play(Write(lab_a), Write(lab_b), Write(lab_c), FadeIn(info1), FadeIn(info2), run_time=1.5)
        self.play(Create(right_mark), FadeIn(info3), run_time=1)
        self.play(
            Create(ang_alpha), Create(ang_beta), Write(lab_alpha), Write(lab_beta), FadeIn(info4),
            run_time=1.5,
        )
        self.wait(1.5)

        # ---- 2. First arrangement --------------------------------------
        T1 = [P(0, 0), P(A, 0), P(0, B)]
        center = P(S / 2, S / 2)
        big_square = Square(side_length=S, color=WHITE, stroke_width=4).move_to(center)

        self.play(
            FadeOut(VGroup(lab_a, lab_b, lab_c, right_mark, ang_alpha, ang_beta, lab_alpha, lab_beta, info)),
            FadeOut(title),
            run_time=1,
        )
        t1 = triangle(T1)
        self.play(Transform(tri, t1), run_time=1.5)
        self.remove(tri)
        self.add(t1)

        # Side labels on the bottom and left edges stay true in both arrangements.
        def edge_labels():
            g = VGroup()
            g.add(MathTex("a", font_size=40, color=A_COLOR).move_to(P(A / 2, -0.35)))
            g.add(MathTex("b", font_size=40, color=B_COLOR).move_to(P(A + B / 2, -0.35)))
            g.add(MathTex("b", font_size=40, color=B_COLOR).move_to(P(-0.35, B / 2)))
            g.add(MathTex("a", font_size=40, color=A_COLOR).move_to(P(-0.35, B + A / 2)))
            ticks = VGroup(
                Line(P(A, -0.12), P(A, 0.12)),
                Line(P(-0.12, B), P(0.12, B)),
            )
            return VGroup(g, ticks)

        sides = edge_labels()
        step1 = Tex(r"Four copies inside a square of side $a + b$", font_size=36)
        step1.move_to(np.array([2.9, 3.3, 0.0]))

        self.play(Create(big_square), FadeIn(sides), FadeIn(step1), run_time=1.5)
        copies = [t1]
        for i in range(1, 4):
            c = t1.copy()
            self.play(Rotate(c, angle=i * PI / 2, about_point=center), run_time=0.9)
            copies.append(c)
        t1, t2, t3, t4 = copies

        inner = Polygon(P(A, 0), P(S, A), P(B, S), P(0, B), color=C_COLOR, stroke_width=4,
                        fill_color=C_COLOR, fill_opacity=0.25)
        c_side = MathTex("c", font_size=40, color=C_COLOR).move_to(
            (P(A, 0) + P(S, A)) / 2 + 0.3 * normalize(np.array([-A, B, 0.0]))
        )
        c_sq = MathTex("c^2", font_size=56, color=C_COLOR).move_to(center)

        r1 = Tex(r"Uncovered: four sides of length $c$", font_size=34)
        r2 = Tex(r"Each corner: $\theta = 180^\circ - (\alpha + \beta) = 90^\circ$", font_size=34)
        r3 = Tex(r"So the uncovered region is a square,", font_size=34)
        r4 = Tex(r"with area $c^2$", font_size=34, color=C_COLOR)
        reasons = VGroup(r1, r2, r3, r4).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        reasons.move_to(np.array([3.0, 0.6, 0.0]))

        self.play(FadeIn(inner), Write(c_side), FadeIn(r1), run_time=1.5)

        # Angles at the corner (a, 0) on the bottom edge.
        p = P(A, 0)
        al = Angle(Line(p, P(0, B)), Line(p, P(0, 0)), radius=0.6, color=ORANGE, stroke_width=5)
        be = Angle(Line(p, P(S, 0)), Line(p, P(S, A)), radius=0.6, color=PURPLE_A, stroke_width=5)
        th = RightAngle(Line(p, P(S, A)), Line(p, P(0, B)), length=0.3, color=C_COLOR)
        al_l = MathTex(r"\alpha", font_size=30, color=ORANGE).move_to(
            Angle(Line(p, P(0, B)), Line(p, P(0, 0)), radius=0.95).point_from_proportion(0.5)
        )
        be_l = MathTex(r"\beta", font_size=30, color=PURPLE_A).move_to(
            Angle(Line(p, P(S, 0)), Line(p, P(S, A)), radius=0.95).point_from_proportion(0.5)
        )
        th_l = MathTex(r"\theta", font_size=30, color=C_COLOR).move_to(p + 0.55 * normalize(np.array([0.15, 1.0, 0])))
        self.play(Create(al), Create(be), Write(al_l), Write(be_l), run_time=1)
        self.play(Create(th), Write(th_l), FadeIn(r2), run_time=1.5)
        self.wait(1)
        self.play(FadeIn(r3), FadeIn(r4), Write(c_sq), run_time=1.5)
        self.wait(2)

        # ---- 3. Second arrangement -------------------------------------
        self.play(
            FadeOut(VGroup(al, be, th, al_l, be_l, th_l, inner, c_side, c_sq, reasons, step1)),
            run_time=1,
        )
        step2 = Tex(r"Move the same four triangles", font_size=36)
        step2.move_to(np.array([2.9, 3.3, 0.0]))
        self.play(FadeIn(step2), run_time=0.8)
        self.play(t3.animate.shift(P(-B, -A) - P(0, 0)), run_time=1.5)
        self.play(t2.animate.shift(P(0, B) - P(0, 0)), run_time=1.5)
        self.play(t4.animate.shift(P(A, 0) - P(0, 0)), run_time=1.5)

        sq_a = Polygon(P(0, B), P(A, B), P(A, S), P(0, S), color=A_COLOR, stroke_width=4,
                       fill_color=A_COLOR, fill_opacity=0.3)
        sq_b = Polygon(P(A, 0), P(S, 0), P(S, B), P(A, B), color=B_COLOR, stroke_width=4,
                       fill_color=B_COLOR, fill_opacity=0.3)
        a_sq = MathTex("a^2", font_size=48, color=A_COLOR).move_to(sq_a)
        b_sq = MathTex("b^2", font_size=56, color=B_COLOR).move_to(sq_b)
        u1 = Tex(r"Uncovered: a square of side $a$", font_size=34)
        u2 = Tex(r"and a square of side $b$,", font_size=34)
        u3 = Tex(r"with total area $a^2 + b^2$", font_size=34)
        u = VGroup(u1, u2, u3).arrange(DOWN, aligned_edge=LEFT, buff=0.3).move_to(np.array([2.8, 0.6, 0.0]))
        self.play(FadeIn(sq_a), Write(a_sq), FadeIn(u1), run_time=1.3)
        self.play(FadeIn(sq_b), Write(b_sq), FadeIn(u2), run_time=1.3)
        self.play(FadeIn(u3), run_time=1)
        self.wait(2)

        # ---- 4. Compare -------------------------------------------------
        second = VGroup(big_square, t1, t2, t3, t4, sq_a, sq_b, a_sq, b_sq, sides)
        self.play(FadeOut(u), FadeOut(step2), run_time=0.8)

        small = 0.62
        o1 = np.array([-6.3, 0.2, 0.0])
        o2 = np.array([-2.3, 0.2, 0.0])
        first_small = VGroup(
            Square(side_length=S * small, color=WHITE, stroke_width=3).move_to(P(S / 2, S / 2, o1, small)),
            triangle([P(0, 0, o1, small), P(A, 0, o1, small), P(0, B, o1, small)]),
            triangle([P(S, 0, o1, small), P(S, A, o1, small), P(A, 0, o1, small)]),
            triangle([P(S, S, o1, small), P(B, S, o1, small), P(S, A, o1, small)]),
            triangle([P(0, S, o1, small), P(0, B, o1, small), P(B, S, o1, small)]),
        )
        first_inner = Polygon(P(A, 0, o1, small), P(S, A, o1, small), P(B, S, o1, small), P(0, B, o1, small),
                              color=C_COLOR, stroke_width=3, fill_color=C_COLOR, fill_opacity=0.25)
        first_lab = MathTex("c^2", font_size=40, color=C_COLOR).move_to(P(S / 2, S / 2, o1, small))
        first_small.add(first_inner, first_lab)

        self.play(
            second.animate.scale(small, about_point=ORIGIN_PT).shift(o2 - ORIGIN_PT),
            run_time=1.5,
        )
        self.play(FadeIn(first_small), run_time=1.2)
        eq_mid = MathTex("=", font_size=60).move_to((o1 + o2) / 2 + np.array([S * small / 2, S * small / 2, 0]))
        head = Tex(r"Same big square, same four triangles", font_size=38).move_to(np.array([0.0, 3.4, 0.0]))
        cap1 = Tex(r"uncovered: $c^2$", font_size=32, color=C_COLOR).move_to(P(S / 2, -1.3, o1, small))
        cap2 = Tex(r"uncovered: $a^2 + b^2$", font_size=32).move_to(P(S / 2, -1.3, o2, small))
        self.play(FadeIn(head), Write(eq_mid), FadeIn(cap1), FadeIn(cap2), run_time=1.2)

        w1 = MathTex(r"\text{uncovered} = (a+b)^2 - 4\cdot\tfrac{1}{2}ab", font_size=36)
        w2 = Tex(r"in both arrangements, so the", font_size=34)
        w3 = Tex(r"uncovered areas are equal:", font_size=34)
        w4 = MathTex(r"c^2 = a^2 + b^2", font_size=40)
        work = VGroup(w1, w2, w3, w4).arrange(DOWN, buff=0.3).move_to(np.array([4.1, 1.1, 0.0]))
        self.play(FadeIn(w1), run_time=1.3)
        self.wait(1)
        self.play(FadeIn(w2), FadeIn(w3), run_time=1.2)
        self.play(Write(w4), run_time=1.2)
        self.wait(1)

        final = MathTex("a^2 + b^2 = c^2", font_size=72, color=YELLOW).move_to(np.array([0.0, -2.6, 0.0]))
        box = SurroundingRectangle(final, color=YELLOW, buff=0.2)
        self.play(Write(final), run_time=1.5)
        self.play(Create(box), run_time=1)
        self.wait(3)
