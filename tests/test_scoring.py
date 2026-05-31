from pathlib import Path

from PIL import Image, ImageDraw

from manimbench.models import RenderResult
from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench.scoring import result_payload, score_task, source_metadata_with_hash
from manimbench.tasks import load_suite


def test_result_payload_records_source_hash_and_render_log():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\n\nclass MainScene(Scene):\n    pass\n"
    render = RenderResult(
        backend="local",
        official=False,
        command=["python", "-m", "manim"],
        exit_code=1,
        timed_out=False,
        stdout="",
        stderr="",
        media_files=[],
        metadata={"media": {}},
    )

    score = score_task(task, "model-a", source, render, Path("/tmp/run"))
    payload = result_payload(task, "model-a", source_metadata_with_hash({}, source), render, score)

    assert payload["source_sha256"]
    assert "render_log" in payload["score"]["artifacts"]
    assert payload["score"]["rubric"]["visual_review"]["fields"]["geometry_correctness"]["status"] == "pending"


def test_source_terms_ignore_comments_and_unused_strings(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = """from manim import *

# Circle Square Triangle Arrow VGroup Transform
class MainScene(Scene):
    def construct(self):
        Text("Circle Square Triangle Arrow VGroup Transform")
        self.add(Text("Basic Manim control"))
"""
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", source, render, tmp_path)

    assert not score.checks["required_source_terms"]["matches"]["Circle"]
    assert "unused_keyword_stuffing" in score.checks["suspicious_source_patterns"]["findings"]
    assert score.automated_score <= 70


def test_placeholder_stub_scene_is_capped(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = """from manim import *

class MainScene(Scene):
    def construct(self):
        # TODO placeholder
        pass
"""
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", source, render, tmp_path)

    assert not score.passed
    assert "placeholder_language" in score.checks["suspicious_source_patterns"]["findings"]
    assert "unimplemented_code" in score.checks["suspicious_source_patterns"]["findings"]
    assert score.automated_score <= 35


def test_blank_rendered_frame_fails_visual_sanity(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    _write_image(tmp_path / "result.png", "blank")
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", _valid_basic_source(), render, tmp_path)

    assert "blank_or_near_blank" in score.checks["visual_sanity"]["findings"]
    assert score.automated_score <= 40


def test_cluttered_rendered_frame_reduces_score(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    _write_image(tmp_path / "result.png", "clutter")
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", _valid_basic_source(), render, tmp_path)

    assert "excessive_foreground_density" in score.checks["visual_sanity"]["findings"]
    assert score.automated_score <= 70


def test_edge_clipped_rendered_frame_reduces_score(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    _write_image(tmp_path / "result.png", "edge")
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", _valid_basic_source(), render, tmp_path)

    assert "possible_edge_clipping" in score.checks["visual_sanity"]["findings"]
    assert score.automated_score <= 80


def test_dense_overlap_fixture_reduces_score(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    _write_image(tmp_path / "result.png", "collision")
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", _valid_basic_source(), render, tmp_path)

    assert "likely_label_or_object_collision" in score.checks["visual_sanity"]["findings"]
    assert score.automated_score <= 82


def test_v03_scoring_enforces_section_and_label_requirements(tmp_path):
    task = load_suite(DEFAULT_SUITE_PATH.parents[1] / "v0.3" / "suite.yaml").tasks[0]
    source = """from manim import *

class MainScene(Scene):
    def construct(self):
        Text("ManimBench V0.3")
        Text("Basic Manim control")
        Text("Calculus derivative integral")
        Text("Linear algebra vector matrix")
        Text("Geometry")
        Text("Probability probability")
        Text("Advanced reasoning Fourier")
        Axes()
        MathTex("x^2")
        Vector([1, 0])
        Matrix([[1, 0], [0, 1]])
        Polygon(ORIGIN, RIGHT, UP)
        Circle()
        Square()
        self.play(Transform(Circle(), Square()))
"""
    render = _successful_render(tmp_path)

    score = score_task(task, "model-a", source, render, tmp_path)

    assert score.checks["minimum_required_labels"]["passed"]
    assert score.checks["required_sections"]["passed"]
    assert score.checks["required_source_terms"]["passed"]


def _successful_render(tmp_path: Path) -> RenderResult:
    if not (tmp_path / "result.png").exists():
        _write_image(tmp_path / "result.png", "normal")
    return RenderResult(
        backend="container",
        official=False,
        command=["python", "-m", "manim"],
        exit_code=0,
        timed_out=False,
        stdout="",
        stderr="",
        media_files=["result.png"],
        metadata={"media": {"result.png": {"fps": 60, "duration_seconds": 5}}},
    )


def _valid_basic_source() -> str:
    return """from manim import *

class MainScene(Scene):
    def construct(self):
        title = Text("Basic Manim control")
        labels = VGroup(
            Text("Circle"),
            Text("Square"),
            Text("Triangle"),
            Text("Arrow"),
            Text("Transform"),
            Text("timeline"),
            MathTex("scale = 2"),
        )
        circle = Circle()
        square = Square()
        triangle = Triangle()
        arrow = Arrow()
        self.add(title, labels, circle, square, triangle, arrow)
        self.play(Transform(circle, square))
"""


def _write_image(path: Path, kind: str) -> None:
    image = Image.new("RGB", (360, 220), "black")
    draw = ImageDraw.Draw(image)
    if kind == "normal":
        draw.rectangle((80, 70, 280, 150), outline="white", width=4)
        draw.line((80, 160, 280, 160), fill="white", width=2)
    elif kind == "clutter":
        draw.rectangle((20, 20, 340, 200), fill="white")
    elif kind == "edge":
        draw.rectangle((0, 0, 359, 219), outline="white", width=18)
    elif kind == "collision":
        for offset in range(0, 90, 5):
            draw.rectangle((145 - offset // 3, 85 - offset // 4, 225 + offset // 3, 135 + offset // 4), outline="white", width=3)
            draw.line((150, 90 + offset // 3, 230, 90 + offset // 3), fill="white", width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
