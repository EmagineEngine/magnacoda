"""The add-on hooks (plugins.py), exercised through fake add-ons instead of installed packages."""

import email.message
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from magnacoda import cli, help_sections, history, plugins
from magnacoda.about import about_text
from magnacoda.cli import main
from magnacoda.pager import reference
from magnacoda.plugins import Edition, StartGroup
from tests.cli.test_screen import _fake_run

BLANKS = ["", "", "", ""]  # wizard: level, AI, color scheme, screen: keep every default


def _load(hooks):
    if isinstance(hooks, BaseException):
        raise hooks  # an add-on that fails to import
    return hooks


@pytest.fixture
def addons(monkeypatch):
    """Call with fake add-on objects to make them look installed: addons(obj, ...), or
    addons(("package", obj), ...) to choose the package name."""

    def install(*items):
        entry_points = []
        for number, item in enumerate(items):
            package, hooks = item if isinstance(item, tuple) else (f"addon{number}", item)
            entry_points.append(
                SimpleNamespace(
                    name=package,
                    dist=SimpleNamespace(name=package, version="1.2"),
                    load=lambda h=hooks: _load(h),
                )
            )
        monkeypatch.delenv("MAGNACODA_PLUGINS", raising=False)
        monkeypatch.setattr(plugins, "_entry_points", lambda: entry_points)
        plugins.reset()

    return install


def _hooks(**hooks):
    return SimpleNamespace(PLUGIN_API=plugins.PLUGIN_API, **hooks)


def _scan(monkeypatch, *args, seen=None):
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen if seen is not None else []))
    return CliRunner().invoke(main, ["scan", "https://a.test", "--fail-on", "none", *args])


def _wizard(monkeypatch, *answers):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    return CliRunner().invoke(main, ["wizard"], input="\n".join(answers) + "\n"), seen


# Finding and loading add-ons


def test_the_off_switch_skips_every_addon(addons, monkeypatch):
    addons(_hooks(edition=lambda: "other"))
    monkeypatch.setenv("MAGNACODA_PLUGINS", "off")
    plugins.reset()
    assert plugins.loaded() == []
    assert plugins.edition() == Edition()


def test_without_addons_the_names_are_magnacoda_s_own(addons):
    addons()
    assert plugins.edition() == Edition()
    assert Edition().display_name == "magnacoda"
    assert "Add-ons" not in about_text()


def test_about_lists_installed_addons(addons):
    addons(("someaddon", _hooks()))
    assert "someaddon 1.2" in about_text()


def test_an_addon_built_for_another_interface_is_skipped_with_a_warning(addons, capsys):
    addons(("oldaddon", SimpleNamespace(PLUGIN_API=plugins.PLUGIN_API + 1)))
    assert plugins.loaded() == []
    assert "Skipped the add-on oldaddon 1.2" in capsys.readouterr().err


def test_an_addon_without_an_interface_number_is_skipped(addons, capsys):
    addons(("bare", SimpleNamespace()))
    assert plugins.loaded() == []
    assert "built for add-on interface None" in capsys.readouterr().err


def test_an_addon_that_fails_to_load_is_skipped_with_a_warning(addons, capsys):
    addons(("broken", ImportError("no module named x")))
    assert plugins.loaded() == []
    assert "Skipped the add-on broken 1.2: it failed to load" in capsys.readouterr().err


def test_an_addon_that_comes_with_magnacoda_goes_by_its_own_name(monkeypatch, capsys):
    hooks = _hooks(
        register_commands=lambda group: group.add_command(click.Command("bundledcmd")),
        help_text=lambda: 5,
    )
    bundled = SimpleNamespace(
        name="bundled", dist=SimpleNamespace(name="magnacoda", version="1.0"), load=lambda: hooks
    )
    monkeypatch.delenv("MAGNACODA_PLUGINS", raising=False)
    monkeypatch.setattr(plugins, "_entry_points", lambda: [bundled])
    plugins.reset()
    assert plugins.loaded()[0].bundled
    plugins.add_commands(main)
    assert "bundled (built in; commands: bundledcmd)" in about_text()
    plugins.help_texts()
    assert "The add-on bundled gave help that is not text" in capsys.readouterr().err


def test_addons_are_found_once_per_process(addons, monkeypatch):
    addons(_hooks())
    calls = []
    original = plugins._entry_points
    monkeypatch.setattr(plugins, "_entry_points", lambda: calls.append(1) or original())
    plugins.loaded()
    plugins.loaded()
    assert calls == [1]


# The edition's names


def test_the_edition_names_the_banner_prompt_about_and_reports(addons, monkeypatch, tmp_path):
    addons(_hooks(edition=lambda: "example"))
    lines = iter(["menu", "shell"])
    prompts = []

    def fake_input(self, prompt=""):
        prompts.append(prompt)
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(cli.Console, "input", fake_input)
    shell = CliRunner().invoke(main, [])
    assert "magnacoda example accessibility scanner" in shell.output
    assert "Already in the magnacoda example shell" in shell.output
    assert (
        prompts[0] == "[italic]magnacoda[/italic] » "
    )  # just magnacoda; the » blue only where colors are known

    assert about_text().startswith("\nmagnacoda example ")

    result = _scan(monkeypatch, "--scans-dir", str(tmp_path), "--show-findings")
    assert "magnacoda example" in result.output  # the terminal report's title
    (checklist,) = tmp_path.glob("*/checklist.md")
    assert "UTC with magnacoda example " in checklist.read_text()


def test_when_two_addons_name_the_edition_the_first_wins_with_a_warning(addons, capsys):
    addons(
        ("first", _hooks(edition=lambda: "one")),
        ("second", _hooks(edition=lambda: "two")),
    )
    assert plugins.edition().display_name == "magnacoda one"
    assert "using first's (ignored: second)" in capsys.readouterr().err


def test_an_edition_hook_that_raises_keeps_the_default_names(addons):
    addons(_hooks(edition=lambda: 1 / 0))
    assert plugins.edition() == Edition()


@pytest.mark.parametrize(
    "word",
    [
        "",
        "Example",
        "two words",
        "example!",
        "averyveryverylongword",
        Edition("example"),
        ("magnacoda example", "x"),
    ],
)
def test_an_edition_can_only_add_one_short_lowercase_word_after_the_name(addons, capsys, word):
    addons(_hooks(edition=lambda: word))
    assert plugins.edition() == Edition()
    assert "not one short lowercase word" in capsys.readouterr().err


def test_the_edition_word_follows_the_name_and_joins_the_prompt(addons):
    addons(_hooks(edition=lambda: "example"))
    assert plugins.edition().display_name == "magnacoda example"


# Commands


def test_an_addon_can_add_a_command(addons):
    @click.command(name="hello")
    def hello():
        click.echo("hello from an add-on")

    addons(_hooks(register_commands=lambda group: group.add_command(hello)))
    result = CliRunner().invoke(main, ["HELLO"])
    assert result.exit_code == 0 and "hello from an add-on" in result.output


def test_an_addon_cannot_replace_a_built_in_command(addons):
    @click.command(name="about")
    def fake_about():
        click.echo("replaced")

    addons(_hooks(register_commands=lambda group: group.add_command(fake_about)))
    result = CliRunner().invoke(main, ["about"])
    assert "replaced" not in result.output
    assert "tried to replace the built-in command 'about'" in result.output


def _commands(*names, hidden=()):
    def register(group):
        for name in names:
            group.add_command(click.Command(name, callback=lambda: None, hidden=name in hidden))

    return register


def _banner(monkeypatch):
    return CliRunner().invoke(main, [], input="menu\n").output


def test_the_banner_lists_commands_that_addons_add_on_a_line_of_its_own(addons, monkeypatch):
    addons(("someaddon", _hooks(register_commands=_commands("favorites", "example"))))
    lines = _banner(monkeypatch).splitlines()
    commands = next(i for i, line in enumerate(lines) if line.startswith("Commands: scan"))
    assert lines[commands + 1] == "Add-on commands: favorites · example"


def test_without_addon_commands_the_banner_has_no_addon_line(addons, monkeypatch):
    addons(_hooks(after_scan=lambda report: None))
    assert "Add-on commands" not in _banner(monkeypatch)


def test_the_banner_shows_five_addon_commands_and_points_to_about_for_more(addons, monkeypatch):
    addons(_hooks(register_commands=_commands("one", "two", "three", "four", "five", "six")))
    line = next(x for x in _banner(monkeypatch).splitlines() if x.startswith("Add-on commands:"))
    assert line == "Add-on commands: one · two · three · four · five · … (all in about)"


def test_hidden_addon_commands_are_not_listed_but_still_work(addons, monkeypatch):
    addons(_hooks(register_commands=_commands("shown", "secret", hidden=("secret",))))
    output = _banner(monkeypatch)
    assert "Add-on commands: shown\n" in output and "secret" not in output
    assert CliRunner().invoke(main, ["secret"]).exit_code == 0


def test_about_lists_each_addons_commands(addons):
    addons(("someaddon", _hooks(register_commands=_commands("favorites"))))
    result = CliRunner().invoke(main, ["about"])
    assert "someaddon 1.2 (commands: favorites)" in result.output


def test_an_addons_help_sections_follow_magnacodas_own_before_the_closing_ones(addons):
    text = "<!-- notes -->\n## favorites\n\n### Saved scans\n\n- `favorites`\n  List them.\n"
    addons(_hooks(help_text=lambda: text))
    names, bodies = help_sections.load_help()
    assert names[-3:] == ["favorites (add-on)", "more info", "about the name"] and names[0] == "overview"
    assert reference.layout(bodies["favorites (add-on)"]) == (
        "Saved scans\n\nFrom the add-on addon0 1.2. It isn't part of *magnacoda*'s own help.\n"
        "  favorites\n      List them."
    )  # no author in its package: no "by"
    output = CliRunner().invoke(main, ["help"]).output  # no terminal here: everything printed
    order = ["Example scans", "Saved scans", "Where to find more", "About the name"]
    assert [output.index(label) for label in order] == sorted(output.index(label) for label in order)


def test_an_addon_cannot_replace_a_built_in_help_section(addons, capsys):
    addons(("someaddon", _hooks(help_text=lambda: "## scan\nmine\n## all\nx\n## extra\nfine\n")))
    names, bodies = help_sections.load_help()
    assert "mine" not in bodies["scan"] and names.count("scan") == 1 and "all" not in names
    assert (
        bodies["extra (add-on)"]
        == "From the add-on someaddon 1.2. It isn't part of *magnacoda*'s own help.\n\nfine"
    )
    err = capsys.readouterr().err
    assert "someaddon has a help section named 'scan'" in err and "named 'all'" in err


def test_an_addons_help_names_it_and_its_author_and_typing_the_section_name_still_finds_it(
    addons, monkeypatch
):
    text = "## tools\n\n### Example tools\n\nThey help.\n"
    addons(("example-tools", _hooks(help_text=lambda: text)))
    real = help_sections.metadata.metadata
    fake = email.message.Message()
    fake["Author-email"] = '"Jane *Doe*" <jane@example.org>'
    monkeypatch.setattr(
        help_sections.metadata, "metadata", lambda name: fake if name == "example-tools" else real(name)
    )
    output = CliRunner().invoke(main, ["help", "tools"]).output  # the name without the mark
    assert " ".join(output.split()) == (
        "Example tools From the add-on example-tools 1.2, by Jane Doe. It isn't part of magnacoda's own "
        "help. They help."
    )  # its own words can't add emphasis or code


def test_help_that_is_not_text_is_ignored_with_a_warning(addons, capsys):
    addons(("someaddon", _hooks(help_text=lambda: ["not", "text"])))
    assert help_sections.load_help()[0][-1] == "about the name"
    assert "someaddon gave help that is not text" in capsys.readouterr().err


def test_one_package_can_provide_several_addons(addons, monkeypatch, capsys):
    entry_points = [
        SimpleNamespace(name=name, dist=SimpleNamespace(name="collection", version="2.0"), load=lambda h=h: h)
        for name, h in (
            ("edition", _hooks(edition=lambda: "example")),
            ("favorites", _hooks(register_commands=_commands("favorites"), edition=lambda: "example")),
            ("reports", _hooks()),
        )
    ]
    monkeypatch.delenv("MAGNACODA_PLUGINS", raising=False)
    monkeypatch.setattr(plugins, "_entry_points", lambda: entry_points)
    plugins.reset()
    result = CliRunner().invoke(main, ["about"])
    assert "collection 2.0 (add-ons: edition, favorites, reports; commands: favorites)" in result.output
    assert result.output.count("collection 2.0") == 1
    assert plugins.edition().display_name == "magnacoda example"
    assert "More than one add-on names the edition" not in capsys.readouterr().err  # they agree


# The wizard


def test_addon_groups_come_before_recent_scans_and_duplicates_show_once(addons, monkeypatch):
    group = StartGroup("Saved", [("Home", "scan https://home.test --level AA")])
    addons(_hooks(wizard_start_options=lambda: [group]))
    history.record("scan https://home.test --level AA")  # same as the add-on's entry: shown once
    history.record("scan https://blog.test --level A")
    result, seen = _wizard(monkeypatch, "recent", "1", "", "", "y")
    assert "saved (1) or recent scans (1)?" in " ".join(result.output.split())  # the add-on's first
    listed = result.output.split("Recent scans", 1)[1].split("Type a number", 1)[0]
    assert "blog.test" in listed and "home.test" not in listed
    assert [c.url for c in seen] == ["https://blog.test"] and seen[0].level == "A"


def test_picking_an_addon_entry_prefills_the_wizard(addons, monkeypatch):
    group = StartGroup("Saved", [("Dark", "scan https://old.test --color-scheme dark")])
    addons(_hooks(wizard_start_options=lambda: [group]))
    result, seen = _wizard(monkeypatch, "saved", "1", "https://new.test", "", "y")
    assert [(c.url, c.color_scheme) for c in seen] == [("https://new.test", "dark")]


def test_wizard_before_run_gets_the_finished_scan_before_the_run_question(addons, monkeypatch):
    received = []

    def before_run(scan):
        received.append(scan)
        click.echo("ADDON-ASKS")

    addons(_hooks(wizard_before_run=before_run))
    result, _ = _wizard(monkeypatch, "https://a.test", *BLANKS, "n")
    assert [s.url for s in received] == ["https://a.test"] and received[0].fail_on == "serious"
    assert result.output.index("ADDON-ASKS") < result.output.index("Run this scan now?")


def test_ctrl_c_inside_an_addon_prompt_cancels_the_wizard(addons, monkeypatch):
    def before_run(scan):
        raise click.Abort()

    addons(_hooks(wizard_before_run=before_run))
    result, seen = _wizard(monkeypatch, "https://a.test", *BLANKS, "y")
    assert result.exit_code != 0 and seen == []


# After a scan


def test_after_scan_gets_the_one_report_of_every_screen(addons, monkeypatch):
    reports = []
    addons(_hooks(after_scan=reports.append))
    result = _scan(monkeypatch, "--screen", "both")
    assert result.exit_code == 0
    assert [r.meta.variants for r in reports] == [["desktop.light", "mobile.light"]]


def test_an_addon_that_raises_never_breaks_a_scan(addons, monkeypatch):
    def broken(report):
        raise RuntimeError("database is locked")

    addons(("flaky", _hooks(after_scan=broken)))
    seen: list = []
    result = _scan(monkeypatch, seen=seen)
    assert result.exit_code == 0 and len(seen) == 1
    assert "The add-on flaky failed in after_scan: database is locked" in result.output


# The --no-addons launch flag


def test_no_addons_at_launch_skips_every_addon(addons, monkeypatch):
    addons(_hooks(edition=lambda: "other"))
    result = CliRunner().invoke(main, ["--no-addons", "about"])
    assert result.exit_code == 0
    assert result.output.startswith("\nmagnacoda ") and "Add-ons" not in result.output


def test_no_addons_works_before_a_scan_and_is_not_recorded(addons, monkeypatch):
    received = []
    addons(_hooks(after_scan=received.append))
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    result = CliRunner().invoke(main, ["--no-addons", "scan", "https://a.test", "--fail-on", "none"])
    assert result.exit_code == 0 and [c.url for c in seen] == ["https://a.test"]
    assert received == []
    assert history.read()[0].command == "scan https://a.test --fail-on none"


def test_no_addons_starts_the_shell_without_addons(addons, monkeypatch):
    addons(_hooks(edition=lambda: "other"))
    monkeypatch.setattr(cli.Console, "input", lambda self, prompt="": (_ for _ in ()).throw(EOFError()))
    result = CliRunner().invoke(main, ["--no-addons"])
    assert "Welcome to magnacoda v" in result.output


def test_no_addons_after_the_command_is_left_to_that_command(addons):
    addons(_hooks())
    result = CliRunner().invoke(main, ["about", "--no-addons"])
    assert result.exit_code != 0  # about has no such option; the flag belongs before the command
    assert plugins.loaded() != []


def test_no_addons_is_not_in_the_help(addons):
    addons()
    result = CliRunner().invoke(main, ["--help"], env={"MAGNACODA_PAGER": "off"})
    assert "--no-addons" not in result.output
