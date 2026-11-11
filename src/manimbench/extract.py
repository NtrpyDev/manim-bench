"""Pull the Python file out of a model's reply."""

from __future__ import annotations

import re

_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([\w+.-]*)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE)
_PYTHON_LANGUAGES = {"", "python", "py", "python3", "py3", "manim"}


def extract_code(reply: str) -> str:
    """Return the code in a reply.

    Models are asked for bare code, but many wrap it in a Markdown fence or add
    a sentence around it. The longest Python-looking fenced block wins. With no
    complete fence, a stray opening or closing fence line is dropped and the
    rest is returned as it is. Code is never rewritten.
    """
    text = reply.replace("\r\n", "\n").strip("\n")
    if not text.strip():
        return ""
    blocks = [(match.group(2).lower(), match.group(3)) for match in _FENCE.finditer(text)]
    python_blocks = [body for language, body in blocks if language in _PYTHON_LANGUAGES]
    candidates = python_blocks or [body for _language, body in blocks]
    scene_blocks = [body for body in candidates if "class " in body or "import " in body]
    if scene_blocks:
        return max(scene_blocks, key=len).strip("\n") + "\n"
    lines = text.split("\n")
    if lines and re.match(r"^[ \t]*(`{3,}|~{3,})", lines[0]):
        lines = lines[1:]
    if lines and re.match(r"^[ \t]*(`{3,}|~{3,})[ \t]*$", lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines).strip("\n") + "\n"
