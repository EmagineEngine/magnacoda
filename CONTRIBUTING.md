# Contributing

[TOC]



## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install-dev   # pip install -e ".[dev]" + playwright install chromium
```

- **In a synced folder** (OneDrive, Dropbox): `python -m venv` may fail with `Function not implemented`, because those folders often don't support the links a venv needs. Create the venv elsewhere, such as `python -m venv ~/venvs/magnacoda`, and point `pip install -e` at this folder.
- **On Windows:** keep the working copy in a short folder outside OneDrive, such as `C:\dev\magnacoda`, since build tools can pass Windows 10's 260-character path limit. Activate the venv with `.venv\Scripts\activate`.
- **The AI tiers** (`--ai explain|semantic`) need an Anthropic API key, only when you use them: `export ANTHROPIC_API_KEY=sk-ant-...`. Add that line to `~/.bashrc` to keep it.

## Running it

```bash
magnacoda scan https://example.com                     # terminal output
magnacoda scan https://example.com -o results.json     # the JSON results in a file too (-o - prints them instead)
magnacoda scan https://example.com --ai explain        # top-10 explanations (needs API key)
magnacoda scan https://example.com --fail-on serious   # CI-style exit-code gating
```

Every option is described in the scan section of `magnacoda help`.

To see the Chromium setup notice without uninstalling Chromium: `magnacoda --force-setup-notice` (also `shell` and `wizard`). It isn't in the help, which is for users.

## Workflow

```bash
make lint             # ruff check/format + mypy on the whole package
make test-unit        # fast, no browser
make test-integration # real headless Chromium against local fixture pages, no internet
make test             # both
make check-wheel      # build the wheel, install it into a fresh environment and try it
```

- **Where things are:** the app is in `magnacoda/`, the add-ons that come with it in `magnacoda_addons/`, and the app's tests in `tests/`.

- **No API key needed:** the AI features are tested with a fake client (`tests/ai_mocked/`). The few `@pytest.mark.live_api` tests run only with `MAGNACODA_TEST_LIVE_AI=1` and a real key, never in CI.
- **No network, no real settings:** `tests/conftest.py` makes every web request fail as if offline and points `XDG_CONFIG_HOME` at a temporary folder. Keep it that way in new tests.
- **The wheel check:** the tests use an editable install, so they can't see a file missing from the package; `make check-wheel` builds the wheel and tries the installed copy.

## Pull requests

GitHub is *magnacoda*'s home, for its issues, pull requests and releases. Every pull request runs the same checks (lint, tests, the wheel check) through the Makefile.

Keep pull requests focused. Run `make lint test check-wheel` before opening one.

Pull requests come from people. Using AI tools while you work is fine, but you send the pull request yourself, you've read and understood every line, and you can answer questions about it. Pull requests opened by bots or AI agents on their own are closed without review.

## Contribution terms

By sending a contribution to *magnacoda* (code, documentation, tests or anything else, in a pull request, a patch or another way), you agree that:

- **It's yours to give.** It is your own work, or you have the right to send it under these terms, and you've said so where it includes someone else's work.
- **It's under the project's license.** Everyone receives it under *magnacoda*'s terms, the Functional Source License (`LICENSE.md`) with its additional permission (`LICENSE-ADDITIONAL-PERMISSION.md`). Like the rest of the version that first includes it, it becomes available under the MIT License two years after that version is published.
- **The licensor may also license it in other ways.** You also give Phillip E. Honstein dba EmagineEngine.com, and anyone *magnacoda* is later transferred to, a perpetual, worldwide, non-exclusive, royalty-free, irrevocable license to use, copy, change, distribute and sublicense your contribution, and to license it under other terms, including commercial ones. If your contribution is covered by a patent of yours, that license includes the patent rights needed to use it.
- **You keep your copyright.** This is a license, not a transfer, so you may still use your contribution in any way you like.

To confirm, add a sign-off line to each commit (`git commit -s`, which adds `Signed-off-by: Your Name <email>`). A contribution without one can't be merged.

## Documentation style

These apply to every document: README, the manual, CONTRIBUTING, the other top-level `.md` files, and the Markdown files under `magnacoda/data/` (help, tips, release notes).

- **The product name is in italics:** *magnacoda*, written `*magnacoda*`, at the start of a sentence too. In commands, addresses and file names it's plain, in backticks: `magnacoda setup`, `magnacoda/`.
- **US English quotation marks:** commas and periods go inside the closing mark ("like this,"); colons and semicolons go outside; a question mark goes inside only when it belongs to the quoted words. Use straight quotes. Anything typed or printed literally goes in backticks, exactly as it is.
- **One line per paragraph:** don't hard-wrap prose; the terminal and editors wrap it.

## Saved scans are never committed

- Scans are saved in `magnacoda-scans` in Documents (`report/paths.py`; tests save in the current folder instead, see `tests/conftest.py`). A scans folder *magnacoda* creates ignores itself (its own `.gitignore` holds `*`), and this repository ignores `magnacoda-scans/` too, for `--scans-dir magnacoda-scans`.
- Files named `results*.json`, `report*.json`, `report*.md`, `checklist*.md` or `myreport*` are ignored as well. Don't commit a scan saved under any other name.

## The command line

- **One group:** `main` in `cli.py` is a `click.Group` (`_DefaultGroup`). `magnacoda` with nothing after it starts the shell.
- **A command word first:** anything else gets one line saying what to type instead (`_not_a_command`): `scan` for an address, `view` for a file, the nearest command for a typo.
- **The shell** runs each line through the same `main` group (`standalone_mode=False`), so commands and messages are the same in both. Two things it handles itself:
  - A command's own `sys.exit()` still raises `SystemExit`; every scan ends with one, for its exit code.
  - Click's errors arrive as `click.ClickException` and are printed with `.show()`.
- **The wizard** runs its scan through Click's normal parsing (`scan_cmd.make_context`, then `invoke`), so it runs exactly the command it shows. Don't use `ctx.invoke(scan_cmd, ...)`, which skips option callbacks and drops options the wizard doesn't ask about.
- **History and settings** are small standard-library modules: `userdir.py` (the settings folder, and `write_private` for atomic, owner-only saves), `preferences.py`, `savedcommand.py` (the stored `scan ...` form, and hiding secrets) and `history.py`.

### Command names

- `pyproject.toml` registers `magnacoda` and two typo aliases, `magnacode` and `magnaconda`, which keep messages saying `magnacoda`.
- Both point into `start.py`, which only loads `cli.py`, so Ctrl+C while it loads ends quietly.
- Neither alias is in the README or the help. Don't add names with dashes.
- `tests/unit/test_entry_points.py` keeps the list exact. Re-run `pip install -e .` after changing it.

### The help text

- Everything `help` shows is in `magnacoda/data/help.md`. The comment at its top explains its Markdown; no code change is needed.
- When you add, rename or remove a `scan` option or a command, update it too, since `tests/cli/test_help.py` fails if one is missing.
- Commands have no `--help` of their own; `scan --help` points to `help`.

### Start-up tips

- The shell shows one tip per start: the `- ` items of `magnacoda/data/tips.md`, in order (`tips.py` remembers the next one).
- Only at start-up, in a terminal, and while `tips = on` under `[display]`.
- Keep the wizard tip first and the "how to turn tips off" tip last; a test checks both.
- Leaving the shell prints a line from `magnacoda/data/goodbyes.md`; about once a week (7 exits and 7 days apart, counted in `farewell-state.json`) it also asks for feedback.

## The pager

The pager in `magnacoda/pager/` is written to be released on its own. It imports nothing from the rest of *magnacoda*, only the standard library and Rich; `tests/unit/test_pager_package.py` checks this.

- `screen.py`: the pager itself (keys, scrolling, the `g` list, the Open list under `o`, Tab through links), standard library only.
- `documents.py`: reads the Open list's documents from a list file in Markdown (its docstring shows the format).
- `formats.py`: every kind of document the pager lays out, so all rendering stays in the pager: Markdown (`markdown.py`), a command reference like a man page (`reference.py`), and plain text. A program hands the pager raw text and says which format it is; a new format goes here.
- `markdown.py`: splits a document at its `##` headings and lays the sections out with Rich. It drops a first-line `# Title` and any table of contents, and turns a link to another section into "text (section N)." A `##` with only a short sentence before two or more `###` is a group: its `###` become the pages, and it a label in the `g` list. Its `outline` lays out the `g` list from the document's own contents list, or else from its headings.
- `reference.py`: the command-reference format, which `help` and `news` use: `## name` sections, term lists with the description under or beside each term, terms never wrapped. `help.md`'s opening comment describes it for writers.
- `files.py`: reads a file safely: at most 2 MB, control codes stripped, binary files refused.
- `options.py`: `PagerOptions`, from the defaults, then a settings file, then the program opening the pager. *magnacoda* uses the `[pager]` section of `preferences.ini` as that file. `save_setting` saves a color chosen with `c`, changing only that line.
- `links.py`: web addresses as terminal hyperlinks (OSC 8); one too long for its line is shortened in the middle, so none is split. Not in code, nor for addresses containing "example."
- `browser.py`: opens a link in a graphical browser, quietly, http and https only. `review` uses it too (the pager never imports *magnacoda*, but *magnacoda* may import the pager).
- `emphasis.py`: *italic* and **bold** in help and news (Markdown gets Rich's own); printed text stays plain.
- `tint.py`: code on a background of its own instead of backticks, where the colors allow.
- `colors.py`: the schemes for `c`; a test checks each has a contrast of at least 7:1.
- `themes.py`: a person's own schemes from `pager-colors.ini`, beside the settings file; only read, never written. Ones below 7:1 or badly written are left out, with the reason shown under `c`.

How *magnacoda* uses it:

- `help`, `readme`, `docs`, `news` and `view FILE` all open in it: `help` and `news` in the reference format, `readme` and `docs` in Markdown, and `view` in Markdown or plain text, depending on the file. `view` starts on the `g` list and keeps the file's own title; `readme` and `docs` drop it, since the title bar says README or Manual.
- The Open list offers `magnacoda/data/documents.md`'s documents, then installed add-ons' license files (`magnacoda/documents.py`). Help, the manual and the README open through their commands; the others like `view`.
- It pages only in a real terminal. Otherwise, with `paging = off` or with `MAGNACODA_PAGER=off`, it prints everything.
- The wheel holds copies of README.md, the manual (`docs/manual.md`) and the other documents on the Open list in `magnacoda/data/` (`pyproject.toml`'s force-include; `documents.SOURCES` finds them in a checkout). Keep the README and the manual in ordinary Markdown, since `tests/unit/test_readme_viewer.py` checks that every section fits 40 to 120 columns. Their contents lists come from their headings, so run `make toc` after changing them.
- The README gets people started; everything else goes in the manual. Link to other files in the repository with relative links, such as `(docs/manual.md#scan-options)` or `(SECURITY.md)`, so they work on GitHub and in any copy of the repository. PyPI shows only the README, so its copy there is built with full links (hatch-fancy-pypi-readme, set up in `pyproject.toml`); text between `<!-- not-on-pypi -->` and `<!-- /not-on-pypi -->` is left out of it. Preview it with `python -m hatch_fancy_pypi_readme`.
- Tests: `tests/unit/test_pager.py` for the logic, `tests/cli/test_help_pager_pty.py` for the real pager in a pseudo-terminal (POSIX only).

## AI engines

- `magnacoda/ai/client.py` is the only place that knows how AI calls are made. `build_client()` returns the Anthropic SDK client or `ClaudeCodeClient`, which runs Claude Code (`claude -p`) on the user's own login.
- Both offer the same call, `client.messages.parse(...)`, so the AI features don't know which one runs.
- `AIConfig.resolve_engine()` in `config.py` picks one (`--ai-engine`; `auto` prefers an API key).
- `ClaudeCodeClient` sends the prompt on standard input and the system prompt in a file, so page data never shows in the process list. It runs with no tools, no saved session and hooks off, from an empty temporary folder.
- Tested on Linux; not yet on macOS and Windows.
- `tests/conftest.py` hides any installed `claude`; `tests/ai_mocked/test_claude_code_client.py` installs a fake one.

## Add-ons

Other packages can extend *magnacoda* without changing it. An add-on registers an entry point in the `magnacoda.plugins` group, pointing at a module (or another object) with `PLUGIN_API = 2` and any of these hooks:

- `register_commands(group)`: add Click commands. They work in the shell too, and can't replace a built-in command. The shell banner and `about` list them; `hidden=True` leaves one out.
- `wizard_start_options()`: return a list of `StartGroup(title, [(label, command), ...], word="...")`. The wizard's first question offers each group by its `word`. Keep labels short; commands use the stored form (`scan URL ...`).
- `wizard_before_run(scan)`: called with the wizard's finished `SavedScan`, before "Run this scan now?" It may ask its own questions.
- `after_scan(report)`: called with each finished `ScanReport`.
- `help_text()`: return Markdown in the format of `magnacoda/data/help.md`. Its sections come after *magnacoda*'s own; one with a name *magnacoda* already uses is skipped. It's called each time help opens. *magnacoda* marks each of its sections as an add-on's, with "(add-on)" after the name in the section list (typing the name alone still finds it) and a line under the section's title naming the add-on, its version and its author, from its package information.

When something goes wrong:

- An add-on that fails to load, has a different `PLUGIN_API`, or raises in a hook gets one warning and is ignored. Ctrl+C in its questions still cancels.
- `MAGNACODA_PLUGINS=off` or `magnacoda --no-addons` skips every add-on, for troubleshooting. `about` lists the ones that loaded.

What an add-on may use from *magnacoda* (everything else is internal and may change):

- `plugins`
- `savedcommand`: `SavedScan`, `parse`, `to_command`, `display_command`, `canonical`, `redact`
- `userdir`: `config_dir`, `write_private`
- `preferences`: `preferences_path`, `AddonSection`, `Setting`, `add_section`, `addon_value` (see "Settings" below)
- `wrapping`: `wrap_for_stream`
- `questions`: `ask`, `ask_yes_no`, `printed` (see "Questions" below)
- `sections`: `new_page(ctx, name)`, for a command that is a section of the shell. In the shell it starts on a page of its own, the banner on top with `name` underlined among the commands, then `name` as a heading; elsewhere nothing changes
- `estimate`: `offer_faster`, the wizard's time estimate, for an add-on that runs a scan
- `findings.models`

Change `PLUGIN_API` only for changes that break existing add-ons, and add a hook only when an add-on needs it. `tests/conftest.py` turns add-ons off for every test; `tests/cli/test_plugins.py` tests the hooks with fake add-ons.

### Writing an add-on

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

### Settings

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

### Questions

- Every question has a blank line above it (above its explanation, when it has one) and one after the answer, never two in a row.
- Ask with `questions.ask(...)` or `questions.ask_yes_no(...)`, never with `click.prompt` or `click.confirm` directly.
- An add-on that prints its own text calls `questions.printed(message)` afterwards, so the spacing stays right.
- `tests/unit/test_questions.py` checks the rule.

### Add-ons that come with *magnacoda*

- They live in `magnacoda_addons/`, one folder each; today `favorites/`. They install beside the app, as the package `magnacoda_addons`.
- Each is registered in *magnacoda*'s own `pyproject.toml` and loaded like any installed add-on, so `--no-addons` turns it off too.
- Each follows the rules for any add-on: it imports only its own files, the standard library, `click` and the parts listed above, and nothing else in *magnacoda* imports it. `tests/addons/test_self_contained.py` checks this, so `favorites/` doubles as a worked example.
- Each keeps its tests in its own `tests/` folder, left out of the wheel.
- After adding a folder or changing the entry points, run `pip install -e .` again.

## How a scan tests a page

### axe-core

- `magnacoda/vendor/axe-core/axe.min.js` is vendored unmodified (MPL-2.0, see `NOTICE.md`). To update it, replace `axe.min.js` and `VERSION` with a pinned release, and capture `tests/fixtures/axe_raw/` again if its output changed.
- In Chromium it runs in an isolated JavaScript world (`browser/axe_injector.run_axe`), so a page that changes built-ins can't break it, and nothing is added to the page. In Firefox it's added as a script tag.

### *magnacoda*'s own tests

After axe-core, in this order:

- **Page features** (`browser/features.py`): counts what's on the page, which decides the relevant manual checks, and keeps up to twenty examples of each. `browser/images.py` photographs up to 30 images for the checklist.
- **Layout** (`browser/layout.py`): text that doesn't fit with WCAG's text spacing, at 200% zoom, and at 320 pixels wide.
- **Keyboard** (`browser/keyboard.py`): presses Tab up to 100 times: visible focus, hidden focus, traps, changes on focus, and the skip link.
- **Fields** (`browser/fields.py`): `autocomplete` and blocked pasting.
- **Forms** (`browser/forms.py`): submits each form empty to see how errors are shown and announced, then changes each field.
- **Motion, hover, keys and widgets** (`browser/media.py`, `hover.py`, `shortcuts.py`, `widgets.py`): moving content, content on hover, single-key shortcuts, and custom controls. Quick scans (`--quick`, or `quick = on` under `[scan]`) leave these out.
- **Where the CSS is set** (`browser/css_sources.py`, `report/css_lines.py`): for problems caused by CSS, the rule, file and line, through Chromium's DevTools protocol and source maps. Chromium only.

Rules for these tests:

- Everything that changes the page runs inside `browser/blocking.py`'s `blocked()`. Navigations get an empty answer and every other request is stopped, so nothing reaches the site.
- Screenshots and CSS locations are never sent to the AI tiers.
- Each test has a test page in `tests/fixtures/pages/`.

### Screens, dark mode and the time estimate

- **Screens:** each screen (`--screen`) is scanned fully in light mode.
- **Dark mode:** then, unless one theme was asked for, `orchestrator.run_dark_pass` loads the page in dark mode. If it looks different, only the contrast, image and focus checks run there.
- **One report:** `findings/merge.py` joins the passes; each finding records where it was seen (`seen_in`, empty when seen everywhere).
- **The time estimate** (`estimate.py`): before a scan, it opens the page once, counts what the tests will visit, and adds up a cost per part, fitted to timed real scans. Re-time a few pages if a test's cost changes; each saved scan's `results.json` has `scan_seconds` beside `estimated_seconds` to compare.
- **Fast tests:** CLI tests run quick scans with the estimate off (`tests/cli/conftest.py`).

### Fix templates and WCAG data

- **Fix templates:** offline fixes are registered in `magnacoda/findings/fix_templates.py` with `@_register("axe-rule-id")`. A rule without one gets a generic fix from axe-core's own help and the W3C Understanding pages, so add a template only when it can say something more concrete.
- **WCAG criteria:** `magnacoda/data/wcag_criteria.json` is generated from the W3C's data by `python scripts/update_wcag_criteria.py`.
- **Manual-check guidance:** `criteria_guidance.json` is written by hand. For each criterion it has a one-line "how to check," a `tier` (`every_page`, `depends`, or `relevant_if` with the page `triggers` that make it relevant), and an optional `follow_up`. A test fails if an A or AA criterion has none.

## The review page

`review` opens a saved scan in the browser.

- **Item IDs** (`report/markdown_export.py`): every tickable checklist line ends with an invisible `<!-- id:... -->`, the same for the same report: `c-` for a criterion, `e-...-fix-` for an element's Fix, `e-...-done-` for its Checked box, `u-` for failures tied to no element.
- **Ticks** (`ticks.py`): reads and sets ticks, changing only that line and saving atomically. The JSON report's `ticked` mirrors them.
- **The page** (`review_page.py`, template `data/review.html`): built on each request, never saved. The checklist is rendered with HTML turned off, so page text can't add markup. The page must stay exemplary, and `tests/integration` scans it at Level AAA in light and dark mode and expects no findings.
- **The server** (`review_server.py`): on `127.0.0.1` only, with a random token in every path, `Host` and `Origin` checks, and a strict Content-Security-Policy. It opens the user's own browser, never the scanning one.
- **Recheck** (`recheck.py`): tests a saved scan's Fix items again, with only the rules that failed, in each screen and theme where they were found, with the scan's login. The `recheck` command and the page's button both use it.
- **Tests:** `tests/unit/test_ticks.py`, `tests/unit/test_review.py` and `tests/integration/test_recheck.py`. The unit tests never open a real browser.

## Releases

### Version numbers

- The version comes from git tags (hatch-vcs), so a commit tagged `v0.1.0` builds as `0.1.0`; later commits build as dev versions such as `0.1.1.dev3+gabc1234`.
- To release, make sure the tests pass, then `git tag v0.1.0` and `git push origin v0.1.0`. The release workflow (`.github/workflows/release.yml`) builds and checks the package, then waits for your approval before publishing it to PyPI. Pre-releases such as `v0.2.0rc1` work too.
- After tagging, re-run `pip install -e .` if you want `--version` in your own environment to catch up.
- `magnacoda about` reads the author, links and license from `pyproject.toml`; re-run `pip install -e .` after editing them too.

### Release notes, news and update checks

- **Release notes:** `magnacoda/data/whats-new.md`, one `## X.Y.Z` section per release, newest first. Add it before tagging, because after people upgrade, the shell announces it once and `news` shows it.
- **News:** a Markdown file at `https://news.magnacoda.dev/v1/news.md` (`NEWS_URL` in `news.py`; `v1` is the format). Each item is a `## YYYY-MM-DD Title` heading with its text. *magnacoda* reads it at most once a day, and only while checks are on.
- **Update checks** ask PyPI about *magnacoda* and each add-on. An answer counts only if the PyPI project lists one of the installed package's web addresses, so keep the GitHub address in `[project.urls]`. Packages with the classifier `Private :: Do Not Upload` are never looked up.
- The `update` command's install detection is in `updater.py`.
