from __future__ import annotations

import ast
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:  # Optional at runtime, declared for full visual scoring installs.
    import numpy as np
except Exception:  # pragma: no cover - exercised only in stripped envs.
    np = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - exercised only in stripped envs.
    Image = None

from manimbench.models import RenderResult, ScoreResult, Task


SCORING_VERSION = "0.4.0"
TEXT_CALLS = {"Text", "Tex", "MathTex", "MarkupText", "Paragraph", "Title"}
STATIC_ASSET_CALLS = {"ImageMobject", "SVGMobject", "VideoMobject", "open", "Image.open"}


@dataclass
class SourceAnalysis:
    syntax_error: str | None = None
    class_names: set[str] = field(default_factory=set)
    import_names: set[str] = field(default_factory=set)
    call_names: set[str] = field(default_factory=set)
    method_names: set[str] = field(default_factory=set)
    visible_text_literals: list[str] = field(default_factory=list)
    all_string_literals: list[str] = field(default_factory=list)
    has_construct: bool = False
    pass_in_construct: bool = False
    not_implemented: bool = False
    scene_activity_calls: int = 0
    mobject_constructor_calls: int = 0


def score_task(
    task: Task,
    model: str,
    source: str,
    render: RenderResult,
    run_dir: Path,
) -> ScoreResult:
    analysis = _analyze_source(source)
    checks: dict[str, Any] = {}
    checks["source_parse"] = {"passed": analysis.syntax_error is None, "error": analysis.syntax_error}
    checks["scene_class"] = _has_scene_class(analysis, task.automated_checks.get("required_scene_class", "MainScene"))
    checks["forbidden_imports"] = _forbidden_imports_absent(
        analysis,
        task.automated_checks.get("forbidden_imports", []),
    )
    checks["required_labels_in_source"] = _label_checks(analysis, task.required_labels)
    checks["minimum_required_labels"] = _minimum_required_labels_check(
        checks["required_labels_in_source"],
        int(task.automated_checks.get("min_required_labels", 0)),
    )
    checks["required_sections"] = _required_sections_check(
        analysis,
        task.automated_checks.get("required_sections", []),
    )
    checks["required_source_terms"] = _required_source_terms_check(
        analysis,
        task.automated_checks.get("required_source_terms", []),
    )
    checks["suspicious_source_patterns"] = _suspicious_source_check(source, analysis, task)
    checks["render_exit_code"] = render.exit_code == 0
    checks["render_not_timed_out"] = not render.timed_out
    checks["media_generated"] = bool(render.media_files)
    checks["fps"] = _fps_check(render, expected=int(task.automated_checks.get("fps", 60)))
    checks["duration"] = _duration_check(
        render,
        max_seconds=int(task.automated_checks.get("max_duration_seconds", task.runtime_limit_seconds)),
    )
    checks["visual_sanity"] = _visual_sanity_check(render, run_dir)
    checks["layout_probe"] = _layout_probe(
        run_dir=run_dir,
        render=render,
        scene_class=str(task.automated_checks.get("required_scene_class", "MainScene")),
    )

    flattened = _flatten_checks(checks)
    passed_count = sum(1 for value in flattened if value)
    raw_score = round(100.0 * passed_count / max(len(flattened), 1), 2)
    automated_score = _apply_score_caps(raw_score, checks)
    passed = all(flattened) and automated_score >= 70.0

    artifacts = {
        "solution": "solution.py",
        "stdout": "logs/stdout.log",
        "stderr": "logs/stderr.log",
        "render_log": "logs/render.log",
    }
    if render.media_files:
        artifacts["media"] = render.media_files[0]

    return ScoreResult(
        task_id=task.id,
        model=model,
        passed=passed,
        automated_score=automated_score,
        checks=checks,
        rubric=_human_review_template(task),
        artifacts={key: str(run_dir / value) for key, value in artifacts.items()},
    )


def result_payload(
    task: Task,
    model: str,
    source_metadata: dict[str, Any],
    render: RenderResult,
    score: ScoreResult,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "scoring_version": SCORING_VERSION,
        "model": model,
        "task": {
            "id": task.id,
            "version": task.version,
            "difficulty": task.difficulty,
            "domains": task.domains,
            "title": task.title,
        },
        "source_metadata": source_metadata,
        "source_sha256": source_metadata.get("source_sha256"),
        "render": asdict(render),
        "score": asdict(score),
    }


def source_metadata_with_hash(source_metadata: dict[str, Any], source: str) -> dict[str, Any]:
    return {**source_metadata, "source_sha256": _sha256_text(source)}


def _analyze_source(source: str) -> SourceAnalysis:
    analysis = SourceAnalysis()
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        analysis.syntax_error = f"{error.msg} at line {error.lineno}"
        return analysis

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []
            self.construct_depth = 0

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                analysis.import_names.add(alias.name)
                analysis.import_names.add(alias.name.split(".", 1)[0])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                analysis.import_names.add(node.module)
                analysis.import_names.add(node.module.split(".", 1)[0])
            for alias in node.names:
                analysis.import_names.add(alias.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            analysis.class_names.add(node.name)
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            in_main_scene = "MainScene" in self.class_stack
            if in_main_scene and node.name == "construct":
                analysis.has_construct = True
                self.construct_depth += 1
                self.generic_visit(node)
                self.construct_depth -= 1
                return
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)  # type: ignore[arg-type]

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str):
                analysis.all_string_literals.append(node.value)

        def visit_Pass(self, node: ast.Pass) -> None:
            if self.construct_depth:
                analysis.pass_in_construct = True

        def visit_Raise(self, node: ast.Raise) -> None:
            name = _call_name(node.exc) if node.exc else ""
            if "NotImplementedError" in name:
                analysis.not_implemented = True
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            call_name = _call_name(node.func)
            if call_name:
                analysis.call_names.add(call_name)
                analysis.call_names.add(call_name.rsplit(".", 1)[-1])
                if "." in call_name:
                    analysis.method_names.add(call_name.rsplit(".", 1)[-1])
                if self.construct_depth and call_name.rsplit(".", 1)[-1] in {"add", "play"}:
                    analysis.scene_activity_calls += 1
                if call_name.rsplit(".", 1)[-1][:1].isupper():
                    analysis.mobject_constructor_calls += 1
                if call_name.rsplit(".", 1)[-1] in TEXT_CALLS:
                    analysis.visible_text_literals.extend(_string_literals_in_call(node))
                if "NotImplementedError" in call_name:
                    analysis.not_implemented = True
            self.generic_visit(node)

    Visitor().visit(tree)
    return analysis


def _call_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Subscript):
        return _call_name(node.value)
    return ""


def _string_literals_in_call(node: ast.Call) -> list[str]:
    values: list[str] = []
    for child in list(node.args) + [keyword.value for keyword in node.keywords]:
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.append(child.value)
        elif isinstance(child, ast.JoinedStr):
            values.extend(part.value for part in child.values if isinstance(part, ast.Constant) and isinstance(part.value, str))
    return values


def _has_scene_class(analysis: SourceAnalysis, scene_class: str) -> bool:
    return scene_class in analysis.class_names


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _forbidden_imports_absent(analysis: SourceAnalysis, forbidden: list[str]) -> dict[str, bool]:
    return {item: not _structural_match(analysis, str(item)) for item in forbidden}


def _suspicious_source_check(source: str, analysis: SourceAnalysis, task: Task) -> dict[str, Any]:
    findings: list[str] = []
    lower_source = source.lower()
    if analysis.syntax_error:
        findings.append("syntax_error")
    if any(term in lower_source for term in ["todo", "placeholder", "fake solution", "stub only", "not implemented"]):
        findings.append("placeholder_language")
    if analysis.pass_in_construct or analysis.not_implemented:
        findings.append("unimplemented_code")
    if not analysis.has_construct or analysis.scene_activity_calls == 0 or analysis.mobject_constructor_calls == 0:
        findings.append("empty_or_inactive_scene")
    if any(_structural_match(analysis, term) for term in STATIC_ASSET_CALLS):
        findings.append("static_or_external_asset_dependency")
    if _has_unused_keyword_stuffing(analysis, task.automated_checks.get("required_source_terms", [])):
        findings.append("unused_keyword_stuffing")
    if any(marker in lower_source for marker in ["random.", "np.random", "numpy.random"]):
        findings.append("randomized_output")
    return {"passed": not findings, "findings": findings}


def _has_unused_keyword_stuffing(analysis: SourceAnalysis, terms: list[str]) -> bool:
    normalized_strings = _normalize_label(" ".join(analysis.all_string_literals))
    for term in terms:
        if _structural_match(analysis, str(term)):
            continue
        if _normalize_label(str(term)) in normalized_strings:
            return True
    return False


def _label_checks(analysis: SourceAnalysis, labels: list[str]) -> dict[str, bool]:
    normalized_literals = [_normalize_label(value) for value in analysis.visible_text_literals]
    return {
        label: any(_normalize_label(label) in literal for literal in normalized_literals)
        for label in labels
    }


def _minimum_required_labels_check(label_checks: dict[str, bool], minimum: int) -> dict[str, Any]:
    observed = sum(1 for passed in label_checks.values() if passed)
    return {"minimum": minimum, "observed": observed, "passed": observed >= minimum}


def _required_sections_check(analysis: SourceAnalysis, sections: list[dict[str, Any]]) -> dict[str, Any]:
    section_results = {}
    for section in sections:
        label = str(section.get("label", ""))
        required_terms = [str(term) for term in section.get("required_terms", [])]
        label_present = _visible_label_present(analysis, label)
        term_matches = {term: _structural_match(analysis, term) or _visible_label_present(analysis, term) for term in required_terms}
        term_present = any(term_matches.values()) if term_matches else True
        section_results[label] = {
            "label_present": label_present,
            "term_present": term_present,
            "term_matches": term_matches,
            "passed": label_present and term_present,
        }
    return {
        "passed": all(item["passed"] for item in section_results.values()) if section_results else True,
        "sections": section_results,
    }


def _required_source_terms_check(analysis: SourceAnalysis, terms: list[str]) -> dict[str, Any]:
    matches = {str(term): _structural_match(analysis, str(term)) for term in terms}
    string_only = {
        str(term): (
            not matches[str(term)]
            and _normalize_label(str(term)) in _normalize_label(" ".join(analysis.all_string_literals))
        )
        for term in terms
    }
    return {
        "passed": all(matches.values()) if matches else True,
        "matches": matches,
        "string_only_matches": string_only,
    }


def _visible_label_present(analysis: SourceAnalysis, label: str) -> bool:
    normalized = _normalize_label(label)
    return any(normalized in _normalize_label(value) for value in analysis.visible_text_literals)


def _structural_match(analysis: SourceAnalysis, term: str) -> bool:
    if not term:
        return False
    names = analysis.class_names | analysis.import_names | analysis.call_names | analysis.method_names
    if term in names:
        return True
    if "." in term:
        parts = term.split(".")
        tail = ".".join(parts[-2:]) if len(parts) >= 2 else term
        return any(name == tail or name.endswith(f".{tail}") or name.endswith(f".{term}") for name in names)
    return any(name.rsplit(".", 1)[-1] == term for name in names)


def _normalize_label(value: str) -> str:
    return (
        "".join(ch for ch in value.lower() if ch.isalnum())
        .replace("alpha", "alpha")
        .replace("theta", "theta")
    )


def _fps_check(render: RenderResult, expected: int) -> dict[str, Any]:
    observed = _first_media_value(render, "fps")
    ok = observed is not None and abs(float(observed) - expected) < 0.25
    return {"expected": expected, "observed": observed, "passed": ok}


def _duration_check(render: RenderResult, max_seconds: int) -> dict[str, Any]:
    observed = _first_media_value(render, "duration_seconds")
    ok = observed is not None and float(observed) <= max_seconds
    return {"max_seconds": max_seconds, "observed": observed, "passed": ok}


def _first_media_value(render: RenderResult, key: str) -> Any:
    media = render.metadata.get("media", {})
    for metadata in media.values():
        if key in metadata and metadata[key] is not None:
            return metadata[key]
    return None


def _visual_sanity_check(render: RenderResult, run_dir: Path) -> dict[str, Any]:
    if render.exit_code != 0 or not render.media_files:
        return {
            "status": "missing_or_failed_render",
            "passed": False,
            "findings": ["missing_media"],
            "metrics": {},
        }
    if Image is None or np is None:
        return {
            "status": "inconclusive",
            "passed": True,
            "reason": "Pillow or numpy is unavailable",
            "metrics": {},
        }

    frames = _load_sample_frames(run_dir / render.media_files[0], run_dir)
    if not frames:
        return {
            "status": "inconclusive",
            "passed": True,
            "reason": "No frames could be sampled from rendered media",
            "metrics": {},
        }

    frame_metrics = [_frame_metrics(frame) for frame in frames]
    metrics = {
        "frames_sampled": len(frame_metrics),
        "avg_contrast": _avg(item["contrast"] for item in frame_metrics),
        "avg_foreground_density": _avg(item["foreground_density"] for item in frame_metrics),
        "max_foreground_density": max(item["foreground_density"] for item in frame_metrics),
        "max_edge_band_density": max(item["edge_band_density"] for item in frame_metrics),
        "max_crowded_cell_density": max(item["max_cell_density"] for item in frame_metrics),
        "max_crowded_cells": max(item["crowded_cells"] for item in frame_metrics),
        "max_component_count": max(item["component_count"] for item in frame_metrics),
    }
    findings: list[str] = []
    if metrics["avg_contrast"] < 4.0 or metrics["avg_foreground_density"] < 0.002:
        findings.append("blank_or_near_blank")
    if metrics["avg_foreground_density"] > 0.48 or metrics["max_foreground_density"] > 0.62:
        findings.append("excessive_foreground_density")
    if metrics["max_edge_band_density"] > 0.24:
        findings.append("possible_edge_clipping")
    if 4.0 <= metrics["avg_contrast"] < 16.0:
        findings.append("low_contrast")
    if metrics["max_crowded_cell_density"] > 0.58 or metrics["max_crowded_cells"] >= 8:
        findings.append("likely_label_or_object_collision")

    return {
        "status": "analyzed",
        "passed": not findings,
        "findings": findings,
        "metrics": {key: round(value, 4) if isinstance(value, float) else value for key, value in metrics.items()},
    }


def _load_sample_frames(media_path: Path, run_dir: Path, count: int = 6) -> list[Any]:
    suffix = media_path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        try:
            return [_load_image(media_path)]
        except Exception:
            return []
    frames = _load_video_frames_with_cv2(media_path, count)
    if frames:
        return frames
    return _load_video_frames_with_ffmpeg(media_path, run_dir, count)


def _load_image(path: Path) -> Any:
    image = Image.open(path).convert("RGB")
    if image.width > 360:
        height = max(1, round(image.height * 360 / image.width))
        image = image.resize((360, height))
    return image


def _load_video_frames_with_cv2(media_path: Path, count: int) -> list[Any]:
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception:
        return []
    capture = cv2.VideoCapture(str(media_path))
    if not capture.isOpened():
        return []
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        capture.release()
        return []
    positions = [round((index + 1) * frame_count / (count + 1)) for index in range(count)]
    frames = []
    for position in positions:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, position))
        ok, frame = capture.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(Image.fromarray(rgb))
    capture.release()
    return frames


def _load_video_frames_with_ffmpeg(media_path: Path, run_dir: Path, count: int) -> list[Any]:
    if not shutil.which("ffmpeg"):
        return []
    with tempfile.TemporaryDirectory(prefix="visual-sanity-", dir=run_dir) as temp:
        pattern = Path(temp) / "frame_%02d.png"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(media_path),
            "-vf",
            "fps=1,scale=360:-1",
            "-frames:v",
            str(count),
            str(pattern),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=60)
        if completed.returncode != 0:
            return []
        return [_load_image(path) for path in sorted(Path(temp).glob("frame_*.png"))]


def _frame_metrics(image: Any) -> dict[str, float | int]:
    assert np is not None
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    gray = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    border = np.concatenate([gray[:5, :].ravel(), gray[-5:, :].ravel(), gray[:, :5].ravel(), gray[:, -5:].ravel()])
    border_background = float(np.median(border))
    global_background = float(np.median(gray))
    diff = np.maximum(np.abs(gray - border_background), np.abs(gray - global_background))
    threshold = max(18.0, float(np.std(gray)) * 0.35)
    mask = diff > threshold
    height, width = mask.shape
    band = max(2, round(min(height, width) * 0.035))
    edge_band = np.concatenate([mask[:band, :].ravel(), mask[-band:, :].ravel(), mask[:, :band].ravel(), mask[:, -band:].ravel()])
    cell_metrics = _grid_metrics(mask)
    return {
        "contrast": float(np.std(gray)),
        "foreground_density": float(np.mean(mask)),
        "edge_band_density": float(np.mean(edge_band)),
        "max_cell_density": cell_metrics["max_cell_density"],
        "crowded_cells": cell_metrics["crowded_cells"],
        "component_count": _component_count(mask),
    }


def _grid_metrics(mask: Any, rows: int = 8, cols: int = 12) -> dict[str, float | int]:
    assert np is not None
    height, width = mask.shape
    densities: list[float] = []
    for row in range(rows):
        y0 = round(row * height / rows)
        y1 = round((row + 1) * height / rows)
        for col in range(cols):
            x0 = round(col * width / cols)
            x1 = round((col + 1) * width / cols)
            densities.append(float(np.mean(mask[y0:y1, x0:x1])))
    return {
        "max_cell_density": max(densities) if densities else 0.0,
        "crowded_cells": sum(1 for density in densities if density > 0.35),
    }


def _component_count(mask: Any) -> int:
    assert np is not None and Image is not None
    image = Image.fromarray((mask.astype("uint8") * 255)).resize((120, 68))
    small = np.asarray(image) > 0
    seen = np.zeros(small.shape, dtype=bool)
    height, width = small.shape
    count = 0
    for y in range(height):
        for x in range(width):
            if not small[y, x] or seen[y, x]:
                continue
            count += 1
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if small[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
    return count


def _layout_probe(run_dir: Path, render: RenderResult, scene_class: str) -> dict[str, Any]:
    if render.backend != "local" or render.exit_code != 0:
        return {
            "status": "inconclusive",
            "passed": True,
            "reason": "Layout probe runs only after successful local renders",
        }
    solution_path = run_dir / "solution.py"
    if not solution_path.exists():
        return {"status": "inconclusive", "passed": True, "reason": "solution.py missing"}
    completed = subprocess.run(
        [sys.executable, "-c", _LAYOUT_PROBE_SCRIPT, str(solution_path), scene_class],
        cwd=run_dir,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "inconclusive",
            "passed": True,
            "reason": (completed.stderr or completed.stdout).strip()[-500:],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "inconclusive", "passed": True, "reason": "invalid probe JSON"}
    findings = []
    if payload.get("labels_outside_frame"):
        findings.append("labels_outside_frame")
    if payload.get("label_overlaps"):
        findings.append("label_overlaps")
    payload["status"] = "analyzed"
    payload["passed"] = not findings
    payload["findings"] = findings
    return payload


_LAYOUT_PROBE_SCRIPT = r"""
import importlib.util
import json
import math
import sys

solution_path = sys.argv[1]
scene_class = sys.argv[2]

spec = importlib.util.spec_from_file_location("manimbench_probe_solution", solution_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from manim import Mobject, config

SceneClass = getattr(module, scene_class)
scene = SceneClass()

def add_candidate(obj):
    if isinstance(obj, Mobject):
        scene.add(obj)
        return
    mob = getattr(obj, "mobject", None)
    if isinstance(mob, Mobject):
        scene.add(mob)
        return
    for mob in getattr(obj, "mobjects", []) or []:
        if isinstance(mob, Mobject):
            scene.add(mob)

def play_stub(*animations, **kwargs):
    for animation in animations:
        add_candidate(animation)

scene.play = play_stub
scene.wait = lambda *args, **kwargs: None
scene.construct()

family = []
for mob in scene.mobjects:
    try:
        family.extend(mob.family_members_with_points())
    except Exception:
        family.append(mob)

frame_w = float(getattr(config, "frame_width", 14.2222))
frame_h = float(getattr(config, "frame_height", 8.0))
left, right = -frame_w / 2, frame_w / 2
bottom, top = -frame_h / 2, frame_h / 2

labels = []
for mob in family:
    name = type(mob).__name__
    if "Text" not in name and "Tex" not in name:
        continue
    try:
        box = [
            float(mob.get_left()[0]),
            float(mob.get_bottom()[1]),
            float(mob.get_right()[0]),
            float(mob.get_top()[1]),
        ]
    except Exception:
        continue
    if all(math.isfinite(value) for value in box):
        labels.append({"type": name, "box": box})

outside = [
    item for item in labels
    if item["box"][0] < left - 0.05 or item["box"][2] > right + 0.05
    or item["box"][1] < bottom - 0.05 or item["box"][3] > top + 0.05
]

overlaps = []
for index, a in enumerate(labels):
    ax0, ay0, ax1, ay1 = a["box"]
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    for b in labels[index + 1:]:
        bx0, by0, bx1, by1 = b["box"]
        x_overlap = max(0.0, min(ax1, bx1) - max(ax0, bx0))
        y_overlap = max(0.0, min(ay1, by1) - max(ay0, by0))
        overlap = x_overlap * y_overlap
        area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
        if area_a and area_b and overlap / min(area_a, area_b) > 0.18:
            overlaps.append({"a": a["type"], "b": b["type"], "overlap_ratio": overlap / min(area_a, area_b)})

print(json.dumps({
    "labels_checked": len(labels),
    "labels_outside_frame": len(outside),
    "label_overlaps": len(overlaps),
}))
"""


def _avg(values: Any) -> float:
    values = list(values)
    return float(sum(values) / max(len(values), 1))


def _apply_score_caps(raw_score: float, checks: dict[str, Any]) -> float:
    cap = 100.0
    if not checks.get("render_exit_code") or not checks.get("media_generated"):
        cap = min(cap, 45.0)
    findings = set(checks.get("suspicious_source_patterns", {}).get("findings", []))
    if {"unimplemented_code", "empty_or_inactive_scene"} & findings:
        cap = min(cap, 35.0)
    if {"placeholder_language", "static_or_external_asset_dependency"} & findings:
        cap = min(cap, 55.0)
    if "unused_keyword_stuffing" in findings:
        cap = min(cap, 70.0)
    visual_findings = set(checks.get("visual_sanity", {}).get("findings", []))
    if "blank_or_near_blank" in visual_findings:
        cap = min(cap, 40.0)
    if "excessive_foreground_density" in visual_findings:
        cap = min(cap, 70.0)
    if "possible_edge_clipping" in visual_findings:
        cap = min(cap, 80.0)
    if "low_contrast" in visual_findings:
        cap = min(cap, 78.0)
    if "likely_label_or_object_collision" in visual_findings:
        cap = min(cap, 82.0)
    layout_findings = set(checks.get("layout_probe", {}).get("findings", []))
    if "labels_outside_frame" in layout_findings:
        cap = min(cap, 82.0)
    if "label_overlaps" in layout_findings:
        cap = min(cap, 76.0)
    return round(min(raw_score, cap), 2)


def _flatten_checks(checks: dict[str, Any]) -> list[bool]:
    flattened: list[bool] = []
    for value in checks.values():
        if isinstance(value, bool):
            flattened.append(value)
        elif isinstance(value, dict):
            if "passed" in value:
                flattened.append(bool(value["passed"]))
            else:
                flattened.extend(bool(item) for item in value.values() if isinstance(item, bool))
    return flattened


def _human_review_template(task: Task) -> dict[str, Any]:
    return {
        "status": "pending",
        "scale": "0-5",
        "visual_review_scale": "pass|partial|fail|pending",
        "visual_review": {
            "schema_version": "0.4.0",
            "overall": "pending",
            "fields": {
                "geometry_correctness": {"status": "pending", "notes": ""},
                "text_readability": {"status": "pending", "notes": ""},
                "label_overlap": {"status": "pending", "notes": ""},
                "layout_composition": {"status": "pending", "notes": ""},
                "pacing": {"status": "pending", "notes": ""},
                "prompt_section_coverage": {"status": "pending", "notes": ""},
                "fake_or_superficial_visuals": {"status": "pending", "notes": ""},
                "final_shareability": {"status": "pending", "notes": ""},
            },
            "critical_issues": [],
            "notes": "",
        },
        "criteria": {
            "mathematical_correctness": None,
            "manim_correctness_and_idiom": None,
            "visual_clarity_and_labeling": None,
            "animation_quality_and_pacing": None,
            "faithfulness_to_prompt": None,
            "mathematical_depth": None,
            "robustness_and_reproducibility": None,
        },
        "task_specific_notes": task.rubric,
        "reviewer_notes": "",
    }
