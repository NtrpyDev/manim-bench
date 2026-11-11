"""Publishing a report into a separate site repository, with a real local git repo."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from conftest import GOOD_SOURCE, FakeRoute, FakeSandbox, good_judge_reply

from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench.pipeline import PipelineRequest, run_all
from manimbench.publish import PublishRequest, publish
from manimbench.registry import JudgePanel
from manimbench.tasks import load_suite

TASK = "coordinate_system_animation"
MODEL = "claude-opus-5-5"
JUDGE = "claude-sonnet-5-5"


def git(repo, *args):
    done = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(scope="module")
def report_bundle(tmp_path_factory):
    """A real report from a fake run: one model, one task, three samples (an official, complete run)."""
    base = tmp_path_factory.mktemp("publish")
    suite = load_suite(DEFAULT_SUITE_PATH)
    task = next(item for item in suite.tasks if item.id == TASK)
    panel = JudgePanel(route="openrouter", judges=[JUDGE], max_frames=3, max_output_tokens=None)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("manimbench.judging.load_judges", lambda: panel)
        result = run_all(
            PipelineRequest(
                models=[MODEL],
                task_ids=[TASK],
                samples=3,
                outputs_dir=base / "outputs",
                runs_dir=base / "runs",
                reports_dir=base / "reports",
                run_id="pub",
                generate_route_factory=lambda _n: FakeRoute(lambda _t, _r: GOOD_SOURCE),
                judge_route_factory=lambda _n: FakeRoute(lambda _t, _r: good_judge_reply(task)),
                sandbox=FakeSandbox(),
            )
        )
    assert result.ok
    return base


@pytest.fixture
def bundle(report_bundle, tmp_path):
    """A private copy per test, so history files and edits never leak between tests."""
    run_dir = tmp_path / "runs" / "pub"
    report_dir = tmp_path / "reports" / "pub"
    shutil.copytree(report_bundle / "runs" / "pub", run_dir)
    shutil.copytree(report_bundle / "reports" / "pub", report_dir)
    return run_dir, report_dir


@pytest.fixture
def site(tmp_path):
    repo = tmp_path / "site"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("site\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "initial")
    return repo


def edit_leaderboard(report_dir, **changes):
    path = report_dir / "data" / "leaderboard.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


def count_files(folder):
    return sum(1 for path in folder.rglob("*") if path.is_file())


def test_draft_publish_creates_branch_copies_bundle_and_commits_once(bundle, site):
    run_dir, report_dir = bundle
    initial = git(site, "rev-parse", "HEAD")
    result = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    assert result.target == "draft"
    assert result.branch == "draft"
    assert result.pushed is False
    assert git(site, "rev-parse", "--abbrev-ref", "HEAD") == "draft"
    assert result.commit == git(site, "rev-parse", "HEAD")
    assert result.commit != initial
    assert git(site, "rev-list", "--count", "HEAD") == "2"
    assert git(site, "log", "-1", "--format=%s") == "Publish draft results from run pub"
    assert result.files == count_files(report_dir / "data") + count_files(report_dir / "videos")
    assert (site / "data" / "leaderboard.json").read_text() == (report_dir / "data" / "leaderboard.json").read_text()
    assert count_files(site / "videos") == count_files(report_dir / "videos") == 3
    assert git(site, "rev-parse", "main") == initial  # main is untouched by a draft
    assert not (site / "index.html").exists()  # only data/ and videos/ are copied
    assert git(site, "status", "--porcelain") == ""


def test_draft_publish_appends_history(bundle, site):
    run_dir, report_dir = bundle
    result = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    lines = (run_dir / "publish-history.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["target"] == "draft"
    assert entry["branch"] == "draft"
    assert entry["commit"] == result.commit
    assert entry["pushed"] is False
    assert entry["published_at"]


def test_publishing_the_same_report_twice_makes_no_second_commit(bundle, site):
    run_dir, report_dir = bundle
    first = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    second = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    assert second.commit == first.commit
    assert git(site, "rev-list", "--count", "HEAD") == "2"
    assert len((run_dir / "publish-history.jsonl").read_text().splitlines()) == 2


def test_a_changed_report_makes_a_new_commit(bundle, site):
    run_dir, report_dir = bundle
    first = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    edit_leaderboard(report_dir, run_id="changed")
    second = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    assert second.commit != first.commit
    assert git(site, "rev-list", "--count", "HEAD") == "3"


def test_republish_removes_files_that_left_the_report(bundle, site):
    run_dir, report_dir = bundle
    publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    stale = next((report_dir / "videos").rglob("*.mp4"))
    relative = stale.relative_to(report_dir)
    stale.unlink()
    publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    assert not (site / relative).exists()
    assert count_files(site / "videos") == 2


def test_live_publish_of_complete_official_report_goes_to_main(bundle, site):
    run_dir, report_dir = bundle
    board = json.loads((report_dir / "data" / "leaderboard.json").read_text())
    assert board["official"] is True and board["complete"] is True
    result = publish(PublishRequest(run_dir=run_dir, target="live", site_repo=site, report_dir=report_dir))
    assert result.branch == "main"
    assert git(site, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(site, "log", "-1", "--format=%s") == "Publish live results from run pub"
    assert (site / "data" / "results.json").exists()


@pytest.mark.parametrize("field", ["complete", "official"])
def test_live_publish_refuses_incomplete_or_unofficial_report(bundle, site, field):
    run_dir, report_dir = bundle
    edit_leaderboard(report_dir, **{field: False})
    before = git(site, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="Refusing to publish live"):
        publish(PublishRequest(run_dir=run_dir, target="live", site_repo=site, report_dir=report_dir))
    assert git(site, "rev-parse", "HEAD") == before
    assert not (site / "data").exists()
    assert not (run_dir / "publish-history.jsonl").exists()


def test_live_publish_error_names_each_problem(bundle, site):
    run_dir, report_dir = bundle
    edit_leaderboard(report_dir, complete=False, official=False)
    with pytest.raises(ValueError) as info:
        publish(PublishRequest(run_dir=run_dir, target="live", site_repo=site, report_dir=report_dir))
    assert "official render settings" in str(info.value)
    assert "not judged" in str(info.value)


def test_allow_incomplete_lets_a_live_publish_through(bundle, site):
    run_dir, report_dir = bundle
    edit_leaderboard(report_dir, complete=False, official=False)
    result = publish(
        PublishRequest(run_dir=run_dir, target="live", site_repo=site, report_dir=report_dir, allow_incomplete=True)
    )
    assert result.branch == "main"
    assert result.commit == git(site, "rev-parse", "HEAD")


def test_draft_publish_does_not_check_completeness(bundle, site):
    run_dir, report_dir = bundle
    edit_leaderboard(report_dir, complete=False, official=False)
    assert publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir)).branch == "draft"


def test_missing_report_data_raises_file_not_found(bundle, site):
    run_dir, report_dir = bundle
    (report_dir / "data" / "tasks.json").unlink()
    with pytest.raises(FileNotFoundError, match="tasks.json"):
        publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=report_dir))
    assert git(site, "rev-list", "--count", "HEAD") == "1"


def test_missing_report_folder_raises_file_not_found(bundle, site, tmp_path):
    run_dir, _report = bundle
    with pytest.raises(FileNotFoundError, match="Build the report first"):
        publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site, report_dir=tmp_path / "nowhere"))


def test_site_path_that_is_not_a_git_repo_raises_file_not_found(bundle, tmp_path):
    run_dir, report_dir = bundle
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(FileNotFoundError, match="not a git repository"):
        publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=plain, report_dir=report_dir))
    assert list(plain.iterdir()) == []


def test_bad_target_raises_value_error(bundle, site):
    run_dir, report_dir = bundle
    with pytest.raises(ValueError, match="draft or live"):
        publish(PublishRequest(run_dir=run_dir, target="staging", site_repo=site, report_dir=report_dir))
    assert git(site, "rev-list", "--count", "HEAD") == "1"
