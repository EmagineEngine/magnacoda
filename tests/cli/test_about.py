from click.testing import CliRunner

from magnacoda import __version__, about
from magnacoda.browser.axe_injector import axe_core_version
from magnacoda.cli import main


def test_about_shows_author_links_version_license_and_axe_version():
    result = CliRunner().invoke(main, ["about"])
    assert result.exit_code == 0
    for expected in (
        f"magnacoda {__version__}",
        "Phillip E. Honstein / EmagineEngine.com",
        "© 2026 Phillip E. Honstein dba EmagineEngine.com",
        "https://magnacoda.dev",
        "Repository:",
        "Issues:",
        "MIT",
        axe_core_version(),
        "not affiliated with or endorsed by",
    ):
        assert expected in result.output, expected


def test_about_works_in_the_shell_and_ignores_capitalization():
    output = CliRunner().invoke(main, ["shell"], input="ABOUT\nexit\n").output
    assert "Author:" in output and "Invalid URL" not in output


def test_about_never_starts_a_page_of_its_own(monkeypatch):
    from magnacoda import teletype

    fed = []
    from rich.console import Console

    monkeypatch.setattr(teletype, "page_feed", lambda console: fed.append("page"))
    monkeypatch.setattr(Console, "is_terminal", property(lambda self: True))
    alone = CliRunner().invoke(main, ["about"]).output
    assert fed == [] and "type a command" not in alone  # a normal terminal: no jump, no banner
    CliRunner().invoke(main, ["shell"], input="about\nexit\n")
    assert fed.count("page") == 1  # the shell's start only: about prints below


def test_about_is_listed_in_the_banner_and_the_help():
    assert (
        "Commands: scan · wizard · help · setup · review · update · about · menu"
        in CliRunner().invoke(main, ["shell"], input="menu\nexit\n").output
    )
    assert "about" in CliRunner().invoke(main, ["help"]).output


def test_about_reads_links_from_the_package_metadata(monkeypatch):
    class Fake(dict):
        def get_all(self, key, default=None):
            return ["Website, https://example.org", "Homepage, https://git.example/x", "Issues, https://i"]

    monkeypatch.setattr(
        about.metadata,
        "metadata",
        lambda name: Fake(Summary="S", Author="Someone", **{"License-Expression": "MIT"}),
    )
    text = about.about_text()
    assert "Someone" in text and "https://example.org" in text
    assert "Repository: https://git.example/x" in text  # falls back to Homepage


def test_about_still_works_when_the_package_is_not_installed(monkeypatch):
    def missing(name):
        raise about.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(about.metadata, "metadata", missing)
    text = about.about_text()
    assert text.startswith(f"\nmagnacoda {__version__}\n\n") and "axe-core:" in text


def test_in_a_terminal_the_name_is_in_italics_in_the_title_and_the_disclaimer(monkeypatch):
    import io

    from rich.console import Console

    from magnacoda import cli

    out = io.StringIO()
    monkeypatch.setattr(
        cli, "Console", lambda: Console(file=out, force_terminal=True, color_system="standard")
    )
    monkeypatch.setenv("MAGNACODA_TYPING", "off")
    CliRunner().invoke(main, ["about"])
    text = out.getvalue()
    assert f"\x1b[3mmagnacoda\x1b[0m {__version__}" in text
    assert "\x1b[3mmagnacoda\x1b[0m is an independent project" in text
