# Contributing

[TOC]

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install-dev   # pip install -e ".[dev]" + playwright install chromium
```

- **In a synced folder** (OneDrive, Dropbox): `python -m venv` may fail with `Function not implemented`, because those folders often don't support the links a venv needs. Create the venv elsewhere, such as `python -m venv ~/venvs/magnacoda`, and point `pip install -e` at this folder.
- **On Windows:** keep the working copy in a short folder outside OneDrive, such as `C:\dev\magnacoda`, since build tools can pass Windows 10's 260-character path limit. Activate the venv with `.venv\Scripts\activate`.

## Running it

```bash
magnacoda scan https://example.com                     # terminal output
magnacoda scan https://example.com -o results.json     # the JSON results in a file too (-o - prints them instead)
magnacoda scan https://example.com --ai explain        # top-10 explanations (needs API key)
magnacoda scan https://example.com --fail-on serious   # CI-style exit-code gating
```

Every option is described in the scan section of `magnacoda help`.

## Workflow

```bash
make lint             # ruff check/format + mypy on the whole package
make test-unit        # fast, no browser
make test-integration # real headless Chromium against local fixture pages, no internet
make test             # both
make check-wheel      # build the wheel and try the installed copy
```

- **Where things are:** the app is in `magnacoda/`, the add-ons that come with it in `magnacoda_addons/`, and the app's tests in `tests/`.
- **No API key needed:** the AI features are tested with a fake client (`tests/ai_mocked/`). The few `@pytest.mark.live_api` tests run only with `MAGNACODA_TEST_LIVE_AI=1` and a real key, never in CI.
- **No network, no real settings:** `tests/conftest.py` makes every web request fail as if offline and points `XDG_CONFIG_HOME` at a temporary folder. Keep it that way in new tests.

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

Scans are saved in `magnacoda-scans` in Documents, and this repository ignores that folder. Files named `results*.json`, `report*.json`, `report*.md`, `checklist*.md` or `myreport*` are ignored as well. Don't commit a scan saved under any other name.

## Changing the code

- **Help:** everything `help` shows is in `magnacoda/data/help.md`. When you add, rename or remove a `scan` option or a command, update it too, since `tests/cli/test_help.py` fails if one is missing.
- **Tips:** the shell shows one tip per start, from the `- ` items of `magnacoda/data/tips.md`. Keep the wizard tip first and the "how to turn tips off" tip last; a test checks both.
- **Page tests:** each test of a page in `magnacoda/browser/` has a test page in `tests/fixtures/pages/`, and anything that changes the page runs inside `blocked()` in `browser/blocking.py`, so nothing reaches the site.
- **Fix templates:** offline fixes are registered in `magnacoda/findings/fix_templates.py` with `@_register("axe-rule-id")`. Add one only when it can say something more concrete than the generic fix.
- **Add-ons:** to write one, see [Writing add-ons](docs/add-ons.md). It doesn't need a pull request.
