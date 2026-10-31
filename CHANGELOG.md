# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Initial commit: a command-line accessibility scanner for a single page URL.
  - Licensed under the Functional Source License, Version 1.1, MIT Future License (FSL-1.1-MIT): free to use, change and share for anything but a competing commercial product or service, and each version becomes MIT-licensed two years after release. An additional permission (`LICENSE-ADDITIONAL-PERMISSION.md`) allows consultants and agencies to use it in client work. Contributions come under the terms in CONTRIBUTING (sign-off on each commit).
  - Detects WCAG 2 issues with axe-core running in a real browser (Chromium or Firefox, via Playwright), including JavaScript-rendered pages and single-page apps.
  - Optional AI reasoning through your own Anthropic API key, or through your Claude Code login so a Claude subscription can be used (`--ai-engine`): plain-language explanations for the top 10 findings, and a second pass for issues axe-core can't detect.
  - Fix suggestions for every finding, from offline templates or AI-written fixes.
  - For problems caused by CSS (links without underlines, low contrast, removed focus outlines, clipped text, small targets), where the style is set: the rule, file and line, and with a source map the original file you edit.
  - Desktop and mobile in one report (`--screen both`, the wizard's default; the phone is a Pixel 8 Pro), with problems found on only one screen pointed out, and dark mode checked on every scan in seconds (contrast, images, keyboard focus; skipped when the page looks the same in dark mode).
  - A checklist of every WCAG criterion in scope, showing what was checked automatically and what still needs a human.
  - Every scan is saved in its own folder (checklist, results and screenshots) in `magnacoda-scans` in your Documents folder, wherever *magnacoda* starts, and ends with a short summary; `--show-findings` shows the full findings in the terminal, `-o FILE` writes a copy of the results for CI, and CI exit codes come from `--fail-on`.
  - An interactive shell, a guided wizard that can start from a recent scan, and a sectioned `help` command that pages like `man`; press `g` and type a section's number or name, `o` to open another document (the manual, the license, a `.md` file of your own), or `/` to find a word or phrase.
  - `shortcut` adds *magnacoda* to the app menu, Start menu (with `Ctrl+Alt+M`) or Applications folder, the desktop, or both; `setup` offers it.
  - Support for add-ons: packages that add commands, wizard steps and after-scan actions (see CONTRIBUTING).
  - `recheck` (and a Recheck fixes button on the review page) tests a saved scan's Fix items again in seconds and updates its checklist in place, also behind a login (the scan's saved login file, or `--cookie`, `--extra-http-header`, `--storage-state`).
  - A file name typed as the address (README.md) is pointed to `view` instead of being scanned as a website.
  - An address that redirects to another site is checked before the scan and asked about at the terminal; the report is of the page actually scanned, with where it came from. A page that moves on to another by itself after a delay fails 2.2.1 Timing Adjustable.
  - In the checklist, each element has one box for its checks (each Fix keeps its own), elements with exactly the same items are listed together as a stack, and an image with no text alternative asks whether it's purely decorative.
  - The review page shows the findings first, open, and the checklist after, closed, each with its count on the line that opens it, and ends with a back-to-top link.
  - `review` returns to the list of saved scans after each one, until you press Enter to leave it.
  - Fix suggestions name what axe-core found on the element, such as the tags a list may not contain, and show code as code.
  - The daily check for updates and news names your version of *magnacoda* and nothing else; news.magnacoda.dev keeps only daily totals of its checks.
  - Radio buttons and checkboxes that share a name are listed once in the checklist, as one question with its options, and a group whose question isn't named for screen readers is listed to fix.
  - axe-core runs apart from the page's own scripts (in Chromium), so pages whose old JavaScript libraries change built-in functions can be scanned.
  - Running a favorite also says how long the scan will take and offers faster settings.
  - Leaving the shell says one of a few words of encouragement, in turn, instead of the same thank-you.
  - A short list of scan options, with the rarely needed ones (browser, exact screen size, one theme only, `--wait` for slow pages, the AI model) in an advanced section of `help`; AI-written fixes come with `--ai`, and an unknown option gets a one-line error.
  - On a long run, the spinner says about how much time is left, and a saved scan ends briefly: what it found, where it's saved, and what to type next.
  - A scan that exits with code 1 because of `--fail-on` says so, and how many problems caused it; one that can't finish says why, and that exit code 2 means nothing was checked. An unexpected failure gives a one-line message instead of a traceback (`-v` shows the details).
  - The wizard asks fewer questions: fix suggestions, output format and fail-on (for scripts and CI) are left at their defaults.
  - The wizard checks the page first and says about how long the scan will take, offering settings that make it faster.
  - `--quick` (or `quick = on` in preferences.ini) leaves out the slowest page tests, about 10 seconds a scan.
  - A saved scan ends with a short summary of what it found (the findings are on its review page; `--show-findings` shows them on screen too) and the command to open it, on a line of its own.
  - `review`: list the scans saved in a folder and review one in your browser, with its pictures and a box to tick on every item (saved into the checklist), or in the help viewer with `--no-browser`.
  - A repeat scan of the same page keeps the items you checked in the previous one; failures found again start unticked.
  - On a page with no audio, video or embedded player, the audio and video criteria are listed as not applicable, already ticked.
  - Hover content, expand and collapse buttons, mouse-only controls and single-key shortcuts are tried (WCAG 1.4.13, 4.1.2, 2.1.1, 2.1.4), content that moves by itself without a pause button is found (2.2.2), and each video's Check items say whether it has an audio description track.
  - The layout is tried at 320 px wide, with WCAG's text spacing and at 200% zoom, for WCAG 1.4.10, 1.4.12 and 1.4.4: elements that make the page scroll sideways and text that gets cut off are listed to fix.
  - Tab is pressed through the page, for WCAG 2.4.7, 2.4.11, 2.1.2, 3.2.1 and 2.4.1: focus that can't be seen, focus hidden under a banner, keyboard traps, changes on focus and a skip link that doesn't work are listed to fix, and the focus order is noted for a person to judge.
  - Password fields are tried for pasting and password managers (WCAG 3.3.8), and fields that seem to ask for the visitor's own details without a matching `autocomplete` value are listed with the value to add (1.3.5).
  - Forms are sent empty, for WCAG 3.3.1, 3.3.3 and 4.1.3: missing error text, error text not tied to its field, and errors screen readers aren't told about are listed to fix, and the messages are shown for a person to judge.
  - Form fields are tried for WCAG 3.2.2 On Input: a field that sends the form, loads another page, opens a window or moves the focus just because its value changed is listed to fix (nothing is sent to the site while this runs).
  - A spinner, with what the scan is doing, while it runs (`spinner = off` in preferences.ini for screen readers).
  - Requires certifi 2026.10.19 or later, which no longer trusts the compromised eMudhra emSign certificates.
  - When a screen reader is running, the shell and wizard offer once to turn off typed-out text, the spinner and paging; `screenreader on` and `off` do it any time.
  - Flags elements that are hidden visually but still reachable by keyboard and screen readers, such as a honeypot form field.
  - Each saved scan gets its own folder, with screenshots of the page's images shown in the checklist next to their alt text.
  - `readme` and `docs`: the README, which gets you started, and the full manual (`docs/manual.md`), in the terminal one section at a time; `view FILE` shows any Markdown or text file the same way. `help` lists every option in a line, and `docs scan` explains them.
  - A tip under the shell's banner each time it starts (`tips = off` in `preferences.ini` turns them off).
  - Favorites, an add-on that comes with *magnacoda*: save scans from the wizard, start them again from its start-up list, and list or delete them with `favorites`.
  - `magnacoda setup` to install the browser and save your API key.
  - Update notices and news: a once-a-day check (which can be turned off) for new versions and news, shown on the shell's banner and by `news`; `update` installs a new version.
