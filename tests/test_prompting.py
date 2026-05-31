from manimbench.paths import DEFAULT_PROMPT_PATH, DEFAULT_SUITE_PATH
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.tasks import load_suite


def test_build_prompt_preserves_master_and_appends_task():
    suite = load_suite(DEFAULT_SUITE_PATH)
    task = suite.tasks[0]
    master = load_master_prompt(DEFAULT_PROMPT_PATH)

    prompt = build_task_prompt(master, task)

    assert prompt.startswith(master)
    assert task.id in prompt
    assert "Required Labels" in prompt
    assert "MainScene" in prompt
