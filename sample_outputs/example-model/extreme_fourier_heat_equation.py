from manim import *


class MainScene(Scene):
    def construct(self):
        title = Text("u_t = alpha u_xx", font_size=34).to_edge(UP)
        axes = Axes(x_range=[0, 6, 1], y_range=[-1.5, 1.5, 1], x_length=8, y_length=3)
        mode1 = axes.plot(lambda x: np.sin(x), color=BLUE)
        mode3 = axes.plot(lambda x: 0.4 * np.sin(3 * x), color=GREEN)
        combined = axes.plot(lambda x: np.sin(x) + 0.4 * np.sin(3 * x), color=YELLOW)
        labels = VGroup(
            Text("u(0,t)=u(L,t)=0", font_size=22).next_to(title, DOWN),
            Text("separation of variables", font_size=20).shift(LEFT * 3 + DOWN * 2.6),
            Text("sine eigenmodes", font_size=20).shift(LEFT * 1 + DOWN * 2.6),
            Text("Fourier coefficients", font_size=20).shift(RIGHT * 1.3 + DOWN * 2.6),
            Text("exponential decay", font_size=20).shift(RIGHT * 3.5 + DOWN * 2.6),
            Text("initial condition", font_size=20).next_to(combined, UP),
            Text("heat diffusion", font_size=20).to_edge(DOWN),
        )
        self.play(Write(title), Write(labels[0]), Create(axes))
        self.play(Create(mode1), Create(mode3), Write(labels[1:5]))
        self.play(Transform(mode3, combined), Write(labels[5:]))
        self.wait(1)
