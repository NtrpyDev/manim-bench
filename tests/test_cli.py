from manimbench.cli import build_parser, main


def test_cli_exposes_planned_commands():
    parser = build_parser()

    assert parser.parse_args(["list-tasks"]).func.__name__ == "cmd_list_tasks"
    assert parser.parse_args(["start"]).func.__name__ == "cmd_start"
    assert parser.parse_args(["list-models"]).func.__name__ == "cmd_list_models"
    assert parser.parse_args(["check-models", "--force", "--show-unregistered"]).func.__name__ == "cmd_check_models"
    assert parser.parse_args(["create-workspaces"]).func.__name__ == "cmd_create_workspaces"
    assert parser.parse_args(["usage-start"]).func.__name__ == "cmd_usage_start"
    assert parser.parse_args(["usage-finish"]).func.__name__ == "cmd_usage_finish"
    assert parser.parse_args(["usage-collect"]).func.__name__ == "cmd_usage_collect"
    assert (
        parser.parse_args(["share-video", "--run-dir", "runs/demo", "--output-dir", "reports/demo/videos"]).func.__name__
        == "cmd_share_video"
    )
    assert parser.parse_args(["review", "init", "--run-dir", "runs/demo"]).func.__name__ == "cmd_review"
    assert parser.parse_args(["generate", "--model", "composer-2-5"]).func.__name__ == "cmd_generate"
    assert (
        parser.parse_args(["generate", "--model", "composer-2-5", "--provider", "cursor"]).provider
        == "cursor"
    )
    assert (
        parser.parse_args(["generate", "--model", "gpt-5-5", "--reasoning-effort", "xhigh"]).reasoning_effort
        == "xhigh"
    )
    assert (
        parser.parse_args(["generate-batch", "--models", "opus-4-8", "--reasoning-effort", "max"]).reasoning_effort
        == "max"
    )
    assert parser.parse_args(["generate-batch", "--models", "composer-2-5,gpt-5-5"]).func.__name__ == "cmd_generate_batch"
    assert parser.parse_args(["publish", "--run-dir", "runs/demo", "--target", "draft"]).func.__name__ == "cmd_publish"
    assert parser.parse_args(["score", "--run-dir", "runs/demo"]).func.__name__ == "cmd_score"
    assert (
        parser.parse_args(
            [
                "run-file-matrix",
                "--model-output",
                "example=outputs/example",
                "--parallel",
                "2",
            ]
        ).func.__name__
        == "cmd_run_file_matrix"
    )
    assert (
        parser.parse_args(
            [
                "render",
                "--solution",
                "solution.py",
                "--task-id",
                "easy_pythagorean_theorem",
            ]
        ).func.__name__
        == "cmd_render"
    )
    assert (
        parser.parse_args(
            [
                "rerun-failed",
                "--previous-run-dir",
                "runs/demo",
                "--model",
                "example",
                "--outputs-dir",
                "outputs/example",
            ]
        ).func.__name__
        == "cmd_rerun_failed"
    )


def test_cli_no_args_launches_tui(monkeypatch):
    import manimbench.tui

    monkeypatch.setattr(manimbench.tui, "launch", lambda: 17)

    assert main([]) == 17
