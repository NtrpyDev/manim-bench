import json

from manimbench.reporting import load_results
from manimbench.visual_review import default_review, merge_review


def test_review_json_merges_into_loaded_results(tmp_path):
    task_dir = tmp_path / "runs" / "demo" / "model-a" / "submission"
    task_dir.mkdir(parents=True)
    result = {
        "schema_version": "0.3.0",
        "model": "model-a",
        "task": {"id": "submission", "title": "Submission", "difficulty": "composite", "domains": []},
        "source_metadata": {},
        "score": {
            "passed": True,
            "automated_score": 90,
            "checks": {"render_exit_code": True, "media_generated": True},
            "rubric": {},
            "artifacts": {},
        },
    }
    (task_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    review = default_review(result)
    review["overall"] = "partial"
    (task_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")

    loaded = load_results(tmp_path / "runs" / "demo")[0]

    assert loaded["visual_review"]["overall"] == "partial"
    assert loaded["score"]["adjusted_visual_score"] == 63.0


def test_merge_review_ignores_missing_review(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text("{}", encoding="utf-8")
    result = {"score": {"automated_score": 100}}

    assert merge_review(result, result_path) == result
