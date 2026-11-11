"""Tests for pulling code out of a model reply."""

from __future__ import annotations

from manimbench.extract import extract_code

CODE = "from manim import *\n\n\nclass MainScene(Scene):\n    def construct(self):\n        pass"


def test_bare_code_gets_one_trailing_newline():
    assert extract_code(CODE) == CODE + "\n"


def test_bare_code_with_trailing_newline_is_unchanged():
    assert extract_code(CODE + "\n") == CODE + "\n"


def test_python_fence():
    assert extract_code(f"```python\n{CODE}\n```") == CODE + "\n"


def test_py_fence():
    assert extract_code(f"```py\n{CODE}\n```") == CODE + "\n"


def test_python3_fence():
    assert extract_code(f"```python3\n{CODE}\n```") == CODE + "\n"


def test_plain_fence_without_language():
    assert extract_code(f"```\n{CODE}\n```") == CODE + "\n"


def test_prose_before_and_after_fence_is_dropped():
    reply = f"Here is the scene you asked for:\n\n```python\n{CODE}\n```\n\nHope this helps."
    assert extract_code(reply) == CODE + "\n"


def test_bash_block_then_python_block_picks_python():
    reply = "```bash\nimport os; pip install manim\n```\n\n" + f"```python\n{CODE}\n```"
    assert extract_code(reply) == CODE + "\n"


def test_several_python_blocks_pick_longest_with_class_or_import():
    short = "import os"
    long_no_class = "x = 1\n" * 50
    reply = f"```python\n{short}\n```\n```python\n{CODE}\n```\n```python\n{long_no_class}```"
    assert extract_code(reply) == CODE + "\n"


def test_unclosed_opening_fence_is_dropped():
    assert extract_code(f"```python\n{CODE}") == CODE + "\n"


def test_unclosed_fence_with_closing_text_only():
    assert extract_code(f"{CODE}\n```") == CODE + "\n"


def test_backticks_inside_string_in_unfenced_code_do_not_truncate():
    code = 'from manim import *\n\n\nclass MainScene(Scene):\n    def construct(self):\n        t = Text("""\n```\nx\n```\n""")\n'
    assert extract_code(code) == code


def test_inline_backticks_in_unfenced_code_do_not_truncate():
    code = 'from manim import *\n\n\nclass MainScene(Scene):\n    def construct(self):\n        Text("```python")\n'
    assert extract_code(code) == code


def test_empty_reply_returns_empty_string():
    assert extract_code("") == ""


def test_whitespace_only_reply_returns_empty_string():
    assert extract_code("  \n\t\n  ") == ""


def test_crlf_line_endings_are_normalized():
    reply = f"```python\r\n{CODE}\r\n```\r\n".replace("\n", "\r\n").replace("\r\r\n", "\r\n")
    assert extract_code(reply) == CODE + "\n"


def test_crlf_bare_code_has_no_carriage_returns():
    assert "\r" not in extract_code(CODE.replace("\n", "\r\n"))


def test_prose_only_reply_is_returned_as_is():
    # Expected: the gates reject it later because it does not parse or lacks the class.
    assert extract_code("Sorry, I cannot do that.") == "Sorry, I cannot do that.\n"
