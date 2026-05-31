from manimbench.cli import build_parser


def test_cli_exposes_planned_commands():
    parser = build_parser()

    assert parser.parse_args(["list-tasks"]).func.__name__ == "cmd_list_tasks"
    assert parser.parse_args(["start"]).func.__name__ == "cmd_start"
    assert parser.parse_args(["create-workspaces"]).func.__name__ == "cmd_create_workspaces"
    assert parser.parse_args(["usage-start"]).func.__name__ == "cmd_usage_start"
    assert parser.parse_args(["usage-finish"]).func.__name__ == "cmd_usage_finish"
    assert parser.parse_args(["usage-collect"]).func.__name__ == "cmd_usage_collect"
    assert (
        parser.parse_args(["share-video", "--run-dir", "runs/demo", "--output-dir", "reports/demo/videos"]).func.__name__
        == "cmd_share_video"
    )
    assert parser.parse_args(["review", "init", "--run-dir", "runs/demo"]).func.__name__ == "cmd_review"
    assert (
        parser.parse_args(["build-site", "--report-dir", "reports/demo", "--output-dir", "site/demo"]).func.__name__
        == "cmd_build_site"
    )
    assert parser.parse_args(["score", "--run-dir", "runs/demo"]).func.__name__ == "cmd_score"
    assert (
        parser.parse_args(
            [
                "run-file-matrix",
                "--model-output",
                "example=sample_outputs/example-model",
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
                "sample_outputs/example",
            ]
        ).func.__name__
        == "cmd_rerun_failed"
    )
