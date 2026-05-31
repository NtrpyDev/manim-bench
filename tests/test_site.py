from pathlib import Path

from manimbench.site import build_site


def test_build_site_copies_template_and_leaderboard(tmp_path):
    report_dir = tmp_path / "reports" / "demo"
    (report_dir / "data").mkdir(parents=True)
    (report_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (report_dir / "data" / "leaderboard.json").write_text(
        '{"schema_version":"0.3.0","models":[{"model":"demo","score":90}]}',
        encoding="utf-8",
    )
    template_dir = tmp_path / "website"
    template_dir.mkdir()
    (template_dir / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (template_dir / "assets").mkdir()
    (template_dir / "assets" / "css").mkdir()
    (template_dir / "assets" / "css" / "style.css").write_text("body{}", encoding="utf-8")

    output_dir = tmp_path / "site" / "demo"
    args = type(
        "Args",
        (),
        {"report_dir": report_dir, "output_dir": output_dir, "template_dir": template_dir},
    )()
    build_site(args)

    assert (output_dir / "index.html").read_text(encoding="utf-8") == "<html>site</html>"
    payload = (output_dir / "data" / "leaderboard.json").read_text(encoding="utf-8")
    assert '"model": "demo"' in payload
    assert "updated_at" in payload
    assert (output_dir / "site_manifest.json").exists()
