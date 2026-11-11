from manim import *


class MainScene(Scene):
    def construct(self):
        # A signed two-decimal readout and a matrix: the record must hold "+1.00" as drawn,
        # and the matrix brackets must not be listed as text.
        tracker = ValueTracker(1)
        readout = DecimalNumber(1, num_decimal_places=2, include_sign=True).to_edge(UP)
        readout.add_updater(lambda mob: mob.set_value(tracker.get_value()))
        matrix = Matrix([[2, 1], [0, 1]]).shift(DOWN)
        self.add(readout, matrix)
        self.wait(1)
        self.play(tracker.animate.set_value(3.5), run_time=15, rate_func=linear)
