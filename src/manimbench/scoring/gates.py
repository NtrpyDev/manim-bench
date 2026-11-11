"""Pass or fail checks. A sample that fails any gate scores zero."""

from __future__ import annotations

import ast
import warnings
from typing import Any

from manimbench.models import RenderResult, RuntimeSettings

# Order matters: the first failed gate names the failure in reports.
GATE_ORDER = ["code_parses", "scene_class", "renders", "video", "duration", "not_blank", "has_motion"]

FAILURE_NAMES = {
    "no_code": "no_code",
    "code_parses": "syntax_error",
    "scene_class": "missing_scene_class",
    "render_timeout": "render_timeout",
    "renders": "render_error",
    "video": "no_video",
    "duration_short": "too_short",
    "duration_long": "too_long",
    "not_blank": "blank_video",
    "has_motion": "static_video",
}


def check_source(source: str, scene_class: str) -> dict[str, Any]:
    """Check the code before spending a render on it."""
    checks: dict[str, Any] = {}
    if not source.strip():
        checks["code_parses"] = {"passed": False, "detail": "The reply contained no code."}
        checks["scene_class"] = {"passed": False, "detail": "The reply contained no code."}
        return {"checks": checks, "failure": "no_code"}
    try:
        with warnings.catch_warnings():
            # A stray backslash in a LaTeX string is a warning, not an error, and still renders.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except SyntaxError as error:
        checks["code_parses"] = {"passed": False, "detail": f"{error.msg} at line {error.lineno}"}
        checks["scene_class"] = {"passed": False, "detail": "The code does not parse."}
        return {"checks": checks, "failure": FAILURE_NAMES["code_parses"]}
    except ValueError as error:  # For example, a null byte in the source.
        checks["code_parses"] = {"passed": False, "detail": str(error)}
        checks["scene_class"] = {"passed": False, "detail": "The code does not parse."}
        return {"checks": checks, "failure": FAILURE_NAMES["code_parses"]}
    checks["code_parses"] = {"passed": True}
    defined = any(isinstance(node, ast.ClassDef) and node.name == scene_class for node in tree.body)
    checks["scene_class"] = {"passed": defined} if defined else {
        "passed": False,
        "detail": f"No top-level class named {scene_class}.",
    }
    return {"checks": checks, "failure": None if defined else FAILURE_NAMES["scene_class"]}


def evaluate_gates(
    source_check: dict[str, Any],
    render: RenderResult | None,
    motion: dict[str, Any] | None,
    runtime: RuntimeSettings,
) -> dict[str, Any]:
    """Combine every gate into one verdict."""
    checks = dict(source_check["checks"])
    failure = source_check["failure"]

    if failure is None and render is not None:
        if render.timed_out:
            checks["renders"] = {"passed": False, "detail": f"Stopped after {runtime.render_timeout_seconds} seconds."}
            failure = FAILURE_NAMES["render_timeout"]
        elif render.exit_code != 0:
            checks["renders"] = {"passed": False, "detail": f"Render exited with code {render.exit_code}."}
            failure = FAILURE_NAMES["renders"]
        else:
            checks["renders"] = {"passed": True}

        duration = render.probe.get("duration_seconds") if render.video else None
        if failure is None:
            if duration is None:
                checks["video"] = {"passed": False, "detail": "The render produced no readable video."}
                failure = FAILURE_NAMES["video"]
            else:
                checks["video"] = {"passed": True}

        if failure is None and duration is not None:
            if duration < runtime.min_duration_seconds:
                checks["duration"] = {"passed": False, "detail": f"{duration:.1f} s is under the {runtime.min_duration_seconds:g} s minimum."}
                failure = FAILURE_NAMES["duration_short"]
            elif duration > runtime.max_duration_seconds:
                checks["duration"] = {"passed": False, "detail": f"{duration:.1f} s is over the {runtime.max_duration_seconds:g} s maximum."}
                failure = FAILURE_NAMES["duration_long"]
            else:
                checks["duration"] = {"passed": True, "detail": f"{duration:.1f} s"}

        if failure is None:
            if not motion or not motion.get("available"):
                checks["video"] = {"passed": False, "detail": "The video could not be read back."}
                failure = FAILURE_NAMES["video"]
            else:
                checks["not_blank"] = {"passed": bool(motion["not_blank"]), "detail": f"blank for {100 * motion['blank_share']:.0f}% of the video"}
                if not motion["not_blank"]:
                    failure = FAILURE_NAMES["not_blank"]
                else:
                    checks["has_motion"] = {
                        "passed": bool(motion["has_motion"]),
                        "detail": f"{motion['active_seconds']:.1f} s of motion, {motion['required_active_seconds']:.1f} s required",
                    }
                    if not motion["has_motion"]:
                        failure = FAILURE_NAMES["has_motion"]

    ordered = {name: checks[name] for name in GATE_ORDER if name in checks}
    return {
        "passed": failure is None and all(name in ordered and ordered[name]["passed"] for name in GATE_ORDER),
        "failure": failure,
        "checks": ordered,
        "not_run": [name for name in GATE_ORDER if name not in ordered],
    }
