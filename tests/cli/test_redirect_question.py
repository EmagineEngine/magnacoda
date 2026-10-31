"""Before scanning, with a person there: an address that redirects to another site is scanned only if
they say so (cli.scan_cmd, browser/redirects.py)."""

from click.testing import CliRunner

from magnacoda import cli
from magnacoda.browser import redirects
from magnacoda.cli import main
from tests.cli.test_screen import _fake_run


def _scan(monkeypatch, tmp_path, answer, landed="https://example.org/", *extra):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: landed)
    args = ["scan", "example.com", "--scans-dir", str(tmp_path), "--fail-on", "none", *extra]
    return CliRunner().invoke(main, args, input=answer), seen


def test_no_scans_nothing(monkeypatch, tmp_path):
    result, seen = _scan(monkeypatch, tmp_path, "n\n")
    text = " ".join(result.output.split())
    assert "example.com redirects to another site: https://example.org/" in text
    assert "Scan example.org instead? [Y/n]" in text and "Cancelled - nothing was scanned." in text
    assert seen == [] and not [p for p in tmp_path.iterdir() if p.is_dir()]


def test_yes_scans_the_other_site_and_says_where_it_came_from(monkeypatch, tmp_path):
    result, seen = _scan(monkeypatch, tmp_path, "\n")  # Enter: yes
    assert [config.url for config in seen] == ["https://example.org/"]
    text = " ".join(result.output.split())
    assert "https://example.com redirected to https://example.org/: this scan is of example.org." in text
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert folder.name.startswith("example.org_")
    title = (folder / "checklist.md").read_text().splitlines()[0]
    assert title == "# Accessibility checklist: https://example.org/ (reached from https://example.com)"


def test_the_same_site_or_a_login_asks_nothing(monkeypatch, tmp_path):
    for landed, extra in (
        ("https://www.example.com/home", ()),
        ("https://example.org/", ("--cookie", "a=b")),
    ):
        result, seen = _scan(monkeypatch, tmp_path, "", landed, *extra)
        assert "instead?" not in result.output and len(seen) == 1


def test_with_no_answer_over_https_the_http_address_is_checked_too(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    landings = {"https://example.com": None, "http://example.com": "https://example.org/"}
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: landings[url])
    args = ["scan", "example.com", "--scans-dir", str(tmp_path), "--fail-on", "none"]
    result = CliRunner().invoke(main, args, input="n\n")
    text = " ".join(result.output.split())
    assert "example.com redirects to another site: https://example.org/" in text and seen == []


def test_a_file_in_this_folder_is_not_scanned_as_a_website(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TRADEMARK.md").write_text("# The name\n")
    result = CliRunner().invoke(main, ["scan", "TRADEMARK.md", "--scans-dir", str(tmp_path / "scans")])
    text = " ".join(result.output.split())
    assert result.exit_code == 2 and seen == []
    assert "type magnacoda view TRADEMARK.md" in text
    assert f"type magnacoda scan {(tmp_path / 'TRADEMARK.md').as_uri()}" in text
    assert "type magnacoda scan https://TRADEMARK.md" in text
