"""magnacoda's documents for the viewer's Open list: its own, then installed add-ons' licenses."""

import re
from importlib import metadata

from magnacoda import documents, plugins


def test_every_document_on_the_list_is_found_in_a_checkout():
    listed = documents.locate(documents.LIST).read_text(encoding="utf-8")
    titles = re.findall(r"^- \[([^\]]+)\]", listed, flags=re.MULTILINE)
    assert [entry.title for entry in documents.entries() if entry.group != documents.ADDONS] == titles
    assert set(documents.SOURCES) <= set(re.findall(r"\]\(([^)]+)\)", listed))  # each one copied is listed


def test_help_the_manual_and_the_readme_open_through_their_commands():
    commands = {entry.title: documents.command_for(entry.path) for entry in documents.entries()}
    assert commands["Help"] == "help" and commands["Manual"] == "docs" and commands["README"] == "readme"
    assert commands["License"] is None


def test_an_installed_add_ons_license_files_are_listed_under_its_name(tmp_path, monkeypatch):
    info = tmp_path / "example_addon-1.0.dist-info"
    (info / "licenses").mkdir(parents=True)
    (info / "licenses" / "LICENSE.md").write_text("# License")
    (info / "METADATA").write_text("Metadata-Version: 2.4\nName: example-addon\nVersion: 1.0\n")
    (info / "RECORD").write_text(
        "example_addon-1.0.dist-info/METADATA,,\nexample_addon-1.0.dist-info/licenses/LICENSE.md,,\n"
    )
    addon = plugins.Plugin("example", "example-addon", "1.0", None)
    monkeypatch.setattr(plugins, "loaded", lambda: [addon])
    monkeypatch.setattr(metadata, "distribution", lambda name: metadata.PathDistribution(info))
    assert [(entry.title, entry.group, entry.path) for entry in documents.addon_licenses()] == [
        ("example-addon: LICENSE.md", documents.ADDONS, info / "licenses" / "LICENSE.md")
    ]
