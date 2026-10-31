import re
import string
from pathlib import Path

from click.testing import CliRunner

from magnacoda import help_sections
from magnacoda.cli import main
from magnacoda.pager import reference
from magnacoda_addons.favorites import commands, messages

SOURCE = Path(commands.__file__).parent

# Every message and the placeholders the code fills in. Editing a message may reword it freely, but
# must keep exactly these {names}.
PLACEHOLDERS = {
    "favorites-empty": set(),
    "favorites-heading": {"count", "limit"},
    "delete-confirm": {"number", "name"},
    "delete-done": {"name", "left"},
    "delete-done-left": {"count"},
    "delete-done-none": set(),
    "delete-cancelled": set(),
    "delete-unknown": {"which"},
    "save-failed": {"reason"},
    "pick-prompt": set(),
    "pick-again": {"count"},
    "run-confirm": {"name"},
}


def test_the_help_adds_a_favorites_section_after_magnacodas_own():
    names, bodies = help_sections.load_help()
    assert names[0] == "overview" and names.index("favorites (add-on)") > names.index("examples")
    body = reference.layout(bodies["favorites (add-on)"])
    assert body.startswith("Favorites\n\nFrom the favorites add-on, which comes with *magnacoda*.\n\n")
    assert "  favorites delete NUMBER\n      Delete one, after asking." in body
    output = CliRunner().invoke(main, ["help"]).output  # no terminal here: everything is printed
    assert output.index("Example scans") < output.index("Favorites")


def test_the_help_mentions_every_command_this_addon_adds():
    body = reference.layout(help_sections.load_help()[1]["favorites (add-on)"])
    terms = [
        line.strip() for line in body.splitlines() if line.startswith("  ") and not line.startswith("   ")
    ]
    names = {name.strip() for term in terms for name in term.split(" / ")}
    for group in (commands.favorites_cmd, commands.fav_cmd, commands.favs_cmd):
        assert group.name in names, group.name
    for sub in commands.favorites_cmd.commands:
        assert f"favorites {sub}" in body, sub


def test_every_message_the_code_uses_is_in_messages_md():
    used = set()
    for path in SOURCE.glob("*.py"):
        used |= set(re.findall(r'messages\.text\(\s*"([a-z0-9-]+)"', path.read_text(encoding="utf-8")))
    assert used == set(PLACEHOLDERS)
    assert set(messages.load()) == set(PLACEHOLDERS)


def test_each_message_keeps_its_placeholders():
    for name, message in messages.load().items():
        found = {field for _, field, _, _ in string.Formatter().parse(message) if field}
        assert found == PLACEHOLDERS[name], name


def test_notes_in_html_comments_are_not_part_of_any_message():
    assert all(
        "<!--" not in message and "HOW IT IS READ" not in message for message in messages.load().values()
    )
