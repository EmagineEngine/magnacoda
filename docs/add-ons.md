# Writing add-ons

[TOC]



## How add-ons work

Other packages can extend *magnacoda* without changing it. An add-on registers an entry point in the `magnacoda.plugins` group, pointing at a module (or another object) with `PLUGIN_API = 2` and any of these hooks:

- `register_commands(group)`: add Click commands. They work in the shell too, and can't replace a built-in command. The shell banner and `about` list them; `hidden=True` leaves one out.
- `wizard_start_options()`: return a list of `StartGroup(title, [(label, command), ...], word="...")`. The wizard's first question offers each group by its `word`. Keep labels short; commands use the stored form (`scan URL ...`).
- `wizard_before_run(scan)`: called with the wizard's finished `SavedScan`, before "Run this scan now?" It may ask its own questions.
- `after_scan(report)`: called with each finished `ScanReport`.
- `help_text()`: return Markdown in the format of `magnacoda/data/help.md`. Its sections come after *magnacoda*'s own; one with a name *magnacoda* already uses is skipped. It's called each time help opens. *magnacoda* marks each of its sections as an add-on's, with "(add-on)" after the name in the section list (typing the name alone still finds it) and a line under the section's title naming the add-on, its version and its author, from its package information.

When something goes wrong:

- An add-on that fails to load, has a different `PLUGIN_API`, or raises in a hook gets one warning and is ignored. Ctrl+C in its questions still cancels.
- `MAGNACODA_PLUGINS=off` or `magnacoda --no-addons` skips every add-on, for troubleshooting. `about` lists the ones that loaded.

## What an add-on may use

An add-on may use only these parts of *magnacoda*. Everything else is internal and may change:

- `plugins`
- `savedcommand`: `SavedScan`, `parse`, `to_command`, `display_command`, `canonical`, `redact`
- `userdir`: `config_dir`, `write_private`
- `preferences`: `preferences_path`, `AddonSection`, `Setting`, `add_section`, `addon_value` (see "Settings" below)
- `wrapping`: `wrap_for_stream`
- `questions`: `ask`, `ask_yes_no`, `printed` (see "Questions" below)
- `sections`: `new_page(ctx, name)`, for a command that is a section of the shell. In the shell it starts on a page of its own, the banner on top with `name` underlined among the commands, then `name` as a heading; elsewhere nothing changes
- `estimate`: `offer_faster`, the wizard's time estimate, for an add-on that runs a scan
- `findings.models`

## Writing an add-on

An add-on is its own Python package, in its own folder or repository. The names below are placeholders. Following `TRADEMARK.md`, its name doesn't contain "magnacoda" or suggest an edition (pro, plus, premium, enterprise, official, team); call it "an add-on for *magnacoda*" instead.

```
example-addon/
  pyproject.toml
  src/example_addon/
    __init__.py
    plugin.py        # PLUGIN_API = 2 and the hooks you use
    help.md          # optional: help sections, returned by help_text()
  tests/
```

`plugin.py` can be as small as this one, which rings the terminal's bell when a scan finishes:

```python
from magnacoda.findings.models import ScanReport

PLUGIN_API = 2


def after_scan(report: ScanReport) -> None:
    print("\a", end="", flush=True)
```

Register it in `pyproject.toml`, so *magnacoda* finds it:

```toml
[project]
name = "example-addon"
dependencies = ["magnacoda"]

[project.entry-points."magnacoda.plugins"]
example = "example_addon.plugin"
```

- **Several add-ons in one package:** give each its own folder and its own entry-point line. `about` shows the package once.
- **Installing:** put it in *magnacoda*'s environment: `pipx inject magnacoda ./example-addon` (add `--editable` while developing), or `pip install -e ./example-addon`. `magnacoda about` then lists it.
- **Testing:** point `XDG_CONFIG_HOME` (and `APPDATA` on Windows) at a temporary folder, so tests never touch the user's real files.

Where an add-on keeps its files:

- **Data it saves for the user:** in `userdir.config_dir()`, under file names that start with the add-on's name. Save them with `userdir.write_private()`.
- **Settings:** in its own section of `preferences.ini` (see "Settings" below).
- **Its help:** in a Markdown file in its own package, read when `help_text()` is called:

  ```python
  from importlib import resources

  def help_text() -> str:
      return (resources.files("example_addon") / "help.md").read_text(encoding="utf-8")
  ```

- **Never** inside the installed *magnacoda* package (an update replaces it), in the scans folder, or in the project being scanned.

## Settings

An add-on never edits `preferences.ini` itself. It declares its section, and *magnacoda* writes it and reads it back:

```python
SECTION = preferences.AddonSection(
    "favorites",
    (preferences.Setting("max", 10, "How many favorites to keep in favorites.md (1 to 100).", low=1, high=100),),
)
limit = preferences.addon_value(SECTION, "max")  # adds the section if missing; a bad value gives the default
```

- A setting is a whole number with its range, on or off, or one word from `choices`, with a one-paragraph comment. Anything else raises `ValueError` when declared.
- The section's name can't be *magnacoda*'s or another add-on's. *magnacoda* only adds it at the end of the file, and leaves alone a file it can't read cleanly.

## Questions

- Every question has a blank line above it (above its explanation, when it has one) and one after the answer, never two in a row.
- Ask with `questions.ask(...)` or `questions.ask_yes_no(...)`, never with `click.prompt` or `click.confirm` directly.
- An add-on that prints its own text calls `questions.printed(message)` afterwards, so the spacing stays right.
- `tests/unit/test_questions.py` checks the rule.

The add-on that comes with *magnacoda*, `magnacoda_addons/favorites/`, follows these rules and makes a worked example.
