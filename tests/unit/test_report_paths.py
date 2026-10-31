from datetime import datetime

import platformdirs
from click.testing import CliRunner

from magnacoda import preferences
from magnacoda.cli import main
from magnacoda.report.paths import default_report_stem, scans_folder

NOW = datetime(2026, 9, 20, 15, 30, 12)


def test_scans_go_to_documents_wherever_magnacoda_starts_unless_the_preference_says_otherwise(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path / "Documents"))
    monkeypatch.chdir(tmp_path)
    assert scans_folder() == tmp_path / "Documents" / "magnacoda-scans"
    output = " ".join(CliRunner().invoke(main, ["review"]).output.split())
    assert f"No saved scans in {tmp_path / 'Documents' / 'magnacoda-scans'}." in output
    preferences.set_value("scan", "folder", "~/elsewhere")
    assert scans_folder().name == "elsewhere" and "~" not in str(scans_folder())


def test_stem_uses_site_and_timestamp():
    assert default_report_stem("https://example.com/", NOW) == "example.com_20260920-153012"


def test_stem_includes_port_and_path_but_no_query_or_unsafe_characters():
    stem = default_report_stem("http://127.0.0.1:8123/dir/page.html?x=1&y=2#frag", NOW)
    assert stem == "127.0.0.1_8123_dir_page.html_20260920-153012"
    assert not any(c in stem for c in "/\\:?&# ")


def test_long_urls_are_truncated():
    stem = default_report_stem("https://example.com/" + "a/" * 100, NOW)
    assert len(stem) <= 60 + len("_20260920-153012")


def test_stem_falls_back_when_url_has_no_usable_site():
    assert default_report_stem("", NOW) == "scan_20260920-153012"


def test_make_self_ignoring_writes_a_star_rule_and_reports_it(tmp_path):
    from magnacoda.report.paths import make_self_ignoring

    assert make_self_ignoring(tmp_path) is True
    assert (tmp_path / ".gitignore").read_text().splitlines()[-1] == "*"
    assert make_self_ignoring(tmp_path) is False  # second call: already there


def test_make_self_ignoring_survives_an_unwritable_folder(tmp_path):
    from magnacoda.report.paths import make_self_ignoring

    assert make_self_ignoring(tmp_path / "does" / "not" / "exist") is False
