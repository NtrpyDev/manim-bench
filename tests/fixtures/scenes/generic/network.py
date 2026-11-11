import urllib.request

from manim import *


class MainScene(Scene):
    def construct(self):
        # The sandbox has no network, so this must fail and take the render with it.
        urllib.request.urlopen("https://example.com", timeout=5).read()
        self.play(Write(Text("The network was reachable")))
        self.wait(20)
