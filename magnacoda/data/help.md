# *magnacoda* help

<!--
This file is everything shown by `help` and `--help`.
Edit it freely; no code changes are needed. It is ordinary Markdown, so it also reads well in Typora or on GitHub, but only the few forms below are understood.

HOW IT IS READ
  * Anything inside an HTML comment, like this one, is a note to editors. It is never shown.
  * A level-2 heading, `## name`, starts a section. The name is short (a few words at most); it is shown in lower case in the pager's key hints and in its numbered section list (the `g` key), not above the section itself.
    `help` pages through the sections in the order they appear here; when paging is off it prints them all, in the same order.
    The first section must be "overview": `help` opens on it.
    Anything above the first section (such as the title) is never shown.
  * A level-3 heading, `### Label`, is shown as a plain line: `Label`.
  * Write each paragraph as ONE long line. It is wrapped to the terminal width when shown, so do not break lines by hand.
  * A list item that starts with a term in backticks is a command, option or example:
        - `--level [A|AA|AAA]`
          Conformance level. Default: AA.
          The term is never wrapped, so keep it short. Put its description on the next line, indented 2 spaces; descriptions are wrapped.
          Text on the same line after the term (- `scan URL` Scan a page) is shown beside it instead, lined up with the other items in that list. It is never wrapped, so keep it short too.
  * **bold**, *italic* and `code` are styled in the pager; printed, they show as written.

KEEP IT COMPLETE
This is the only help: commands have no --help of their own. If you add or rename a scan flag or a command, update the matching section below (tests check that every scan flag and every command is mentioned).
-->

## overview

*magnacoda* is a WCAG 2 accessibility scanner for developers and content managers comfortable in a terminal. It explains what it finds and how to fix it, so you can act on the results right away and learn as you go.

- Open a terminal and run *magnacoda* with no arguments to start an interactive shell. Let the **wizard** ask a few plain-language questions and build the scan for you. To learn how to open a terminal on your computer, type `docs starting`.
- Or scan a page directly from the command line with `magnacoda scan URL [OPTIONS]`. The URL can be short, such as example.com or localhost:3000: *magnacoda* fills in the rest.
- To use the AI tiers you can provide your own Anthropic API key (`setup` can save one for you), or use Claude Code if it is installed and logged into your Claude subscription.
- AI works with *magnacoda* both ways: your AI coding agent can run it, and it can use AI itself. To see both in one round of work on a page, type `docs full example`.

In the help viewer, press `g` to **go** to a section, or `Space` to go to the next page and learn about the **wizard**.

The help viewer shows its keys at the bottom of the screen. To open a page this help mentions, such as `docs starting`, press `o`, type it and press `Enter`. For other commands, first press `q` or `Esc` to close the help viewer.

## wizard

### The guided wizard

This is the easiest way to start, and you don't need to know any options. Type `wizard` in the shell, or run `magnacoda wizard`.

The wizard asks for the page's address, then a few questions: the WCAG level, AI reasoning, and which screens to test (a desktop and a phone, unless you choose only one). Dark mode is checked, without asking. Each question is explained in a line and has a default, which you accept by pressing `Enter`.

Before scanning, the wizard shows the full command it built, so you can learn the options over time. It also estimates how long the scan will take and offers settings that make it faster. Nothing runs until you say so.

Next time, the wizard will ask whether to start a new scan or a recent one. If you type recent, you can pick a scan by number to run it again, on the same page or on a new address that you type.

## url-rules

### URL rules

When you type the URL, *magnacoda* fills in https:// or http:// if you omit it, and always reports which address it will scan. History and saved scans keep the full address.

- `https://example.com`
  A full address is used exactly as typed. file:///path/page.html scans a file on your computer.
- `example.com`
  Becomes https://example.com. If that cannot connect, *magnacoda* tries http://example.com once, as browsers do (but without --cookie or --extra-http-header, to avoid sending unencrypted private data).
- `localhost:3000`
  Local addresses are recast as http:// addresses. Examples are localhost, 127.0.0.1, home or office network addresses such as 192.168.1.20, and names ending in .localhost, .local or .test.
- `mysite`
  A one-word name, such as one that you have added to your computer's *hosts* file, becomes http://mysite, if a computer by that name is found. Otherwise *magnacoda* will report that no computer was found, under the assumption that it was a mistyped command; you can force the scan by typing http://mysite.
- `mysite:8080`
  A one-word name with a port always gets recast as http://mysite:8080.
- `FILENAME.md`
  A file name can look like a web address. In this case, .md is Moldova's domain. If a file by that name is in the current folder, *magnacoda* doesn't run the scan. Instead it explains how to read the file, scan it, or scan a website with the same name.
- `1`
  A number on its own is never an address. Therefore, if a number on its own is input at the shell's prompt, *magnacoda* will provide a short explanation.

If an address redirects to another site (example.com to example.org) and you're at the terminal, *magnacoda* asks whether to scan the other site (the site *forwarded to*) instead. When *magnacoda* is running as part of CI or scripts where there is no opportunity to prompt the user, it scans the page that was *reached*, and mentions the page it was redirected from.

## usage

*magnacoda* can be used from the command line or from within its shell.

To learn how to open a terminal on your computer, type `docs starting`.

### Usage (outside the shell):

- `magnacoda [OPTIONS]`
  Start the interactive shell.
- `magnacoda scan URL [OPTIONS]`
  Scan a page.
- `magnacoda COMMAND [ARGS]`
  Run one command: scan, wizard, setup, shortcut, screenreader, review, recheck, shell, news, update, about, help, readme, docs or view.

The commands and options sections list what's available.

### Usage (inside the shell):

The shell is *magnacoda*'s REPL (read-eval-print loop). To start it, type `magnacoda` on its own; then you type commands without `magnacoda` in front, as often as you like.

The banner at the top lists the commands, and a short tip appears under it, a different one each time. You can turn tips off with `tips = off` under `[display]` in preferences.ini.

- `scan`, `wizard`, `help`
  Commands are single words, and capitalization doesn't matter, so `help` and `Help` both work.
- `--screen mobile`
  Options start with dashes and fine-tune a command, mostly scan, as in `scan example.com --screen mobile`. The scan section lists them all.
- `q`, `Ctrl+C`, `clear`
  Cancel any question.
- `Enter`
  Takes what the brackets show: `[back]`, a default, or the capital letter in `[Y/n]` or `[y/N]`.
- `Ctrl+Shift++`, `Ctrl+-`
  Your terminal's zoom makes the text bigger or smaller (in Windows Terminal, `Ctrl++`; on macOS, `Cmd++`). To start bigger every time, choose a larger font in your terminal's settings.

Like an old terminal printer, the shell never erases anything. Each command's output prints below the last, and older text scrolls up into your terminal's *scrollback*, so you can always bring it back into view with a spin of the mouse wheel or a swipe of the touchpad.

## commands

### Commands (inside the shell, or after entering the shell with `magnacoda`):

- `scan URL [OPTIONS]`
  Scan a page for WCAG accessibility issues. Every scan flag is listed in the scan section of `help`.
- `wizard`
  Answer a few questions, see the equivalent command, then run the scan. The wizard section tells you more.
- `setup`
  Install the Playwright Chromium browser and choose how the AI tiers run: with your Claude plan through Claude Code, or with an Anthropic API key, which it can save for you. To delete a saved key later, type `setup --forget-key`.
- `shortcut`, `shortcut remove`
  Add a shortcut to your app menu (on Windows, the Start menu, where `Ctrl+Alt+M` opens it too; on macOS, Applications), your desktop, or both. Uninstalling *magnacoda* leaves the shortcuts behind, so remove them first.
- `screenreader on`, `screenreader off`
  With a screen reader, `on` turns off what reads poorly with one: text typed out a little at a time, the spinner and paging. `off` turns them back on, and `screenreader` alone says which are on.
- `review [FOLDER] [--no-browser]`
  List your saved scans, newest first, so you can pick one by number and review it in your browser. To look in another folder, add its name; to read it in the help viewer instead of your browser, add `--no-browser` (it also opens there when there's no browser). The help viewer only shows it; to tick items, use your browser or a Markdown editor. For more, type `docs reviewing`.
- `recheck [FOLDER]`
  Once you've fixed some problems, pick the scan, as with review, and *magnacoda* tests just those problems again, in a few seconds. Each fix it confirms is ticked in the checklist. To recheck one scan without choosing, give its folder. For more, type `docs reviewing`.
- `news`
  Show available updates, what's new in your version, and news about *magnacoda*, one screen at a time. When there's something new, the shell's banner mentions it in your first shell of the day, on up to three days.
- `update`
  Update *magnacoda*, and any add-ons published on PyPI, to the latest version. It shows you what it will run and asks first (`update --yes` doesn't ask). For more, type `docs updates`.
- `about`
  Show the author, copyright, website, repository, version and license, and where to report problems.
- `help`, `help NAME`
  Browse all of the help, one screen at a time. You can type `help scan`, and it will open at the scan section. The keys are shown at the bottom of the screen; for more, type `readme help`.
- `readme`, `readme NAME`
  Read the README, which gets you started, in this same viewer. You can type `readme quick start`, and it will open at that section.
- `docs`, `docs NAME`
  Read the manual, which covers everything, in this same viewer. You can type `docs scan`, and it will open at the scan options; `manual` works too. Both are the copies that came with your version, so they work offline.
- `view FILE`, `view FILE NAME`
  Read any Markdown or text file in the help viewer, such as a scan's `checklist.md`. Add a section's name to open it there. The documents that come with *magnacoda*, such as `CONTRIBUTING.md`, open from any folder.

### Only inside the shell:

- `clear / cls`
  Feed a fresh page, the way a printer does. What was on screen scrolls up into the scrollback, where nothing is erased, and the banner is shown at the top.
- `details`
  When something goes wrong that *magnacoda* didn't expect, this shows you the full details, to look into it or to report it. Cookie and header values are left out.
- `exit / quit / q`
  Leave the shell (`Ctrl+D` also works). `q` and `Ctrl+C` ask first, since they're easy to press once too often.

## options

### Options (when launching):

- `--help`
  Show the help, the same as the `help` command.
- `--version`
  Show the version number.

## scan

### Options for scan

When launching:

- `magnacoda scan URL [OPTIONS]`

From inside the shell:

- `scan URL [OPTIONS]`

### With only an address, or none

- `scan`
  Asks for the address.
- `scan example.com`
  Shows the default settings and asks before it starts. Press `Enter` to scan, or `n` to stop. Scanned it before? Its saved settings come first.
- `q`, `clear`
  Cancel at any question, as `Ctrl+C` does.

The address can be short; the url-rules section explains how.

### What to check

- `--level [A|AA|AAA]`
  Conformance level. Default: AA.
- `--wcag-version [2.0|2.1|2.2]`
  WCAG version. Default: 2.2.
- `--screen [desktop|mobile|both]`
  A desktop screen, a phone, or both in one scan. Default: desktop.
- `--quick`, `--thorough`
  Leave out, or run, the slowest tests (about 10 seconds a scan). Default: thorough.

### AI reasoning (needs your own Anthropic API key, or Claude Code logged in to your Claude subscription)

- `--ai [off|explain|semantic]`
  How much AI to use. `off`: none. `explain`: the AI explains the 10 most important problems and how to fix them. `semantic`: the same, and the AI also reads the page's alt text, headings and link text to judge whether they make sense, which rule checks can't. Default: off.
- `-y, --yes`
  Accept the AI data-sharing question in advance (for scripts).

### Output and CI

- `--show-findings`
  Also show the full findings here.
- `-o, --output PATH`
  Also write the results as JSON to this file; -o - prints them.
- `--fail-on [none|minor|moderate|serious|critical]`
  Exit with code 1 at or above this severity. Default: serious.
- `-v, --verbose`
  More detail; repeat for more.

### Pages behind a login

- `--storage-state PATH`
  Start from a saved Playwright login session.
- `--cookie NAME=VALUE`
  Set a cookie before loading the page. Repeat for several.
- `--extra-http-header KEY=VALUE`
  Send an extra HTTP header. Repeat for several.

### Pages that need help to load

- `--wait-for-selector TEXT`
  Wait until this CSS selector appears.
- `--ignore-https-errors`
  Continue past invalid or self-signed certificates.

The advanced section has the rarely needed options. For more about each option, type `docs scan`.

## advanced

### Advanced scan options

- `--wait SECONDS`
  Give a slow page this much longer to load and settle.
- `--color-scheme [light|dark|both]`
  Scan one theme only, fully. Default: both.
- `--device TEXT`
  Emulate one Playwright device, such as `iPhone 13`.
- `--viewport WIDTHxHEIGHT`
  Exact window size. Desktop is 1280x720.
- `--user-agent TEXT`
  Send this User-Agent string.
- `--browser [chromium|firefox|webkit]`
  Browser engine. Default: chromium.
- `--headful`
  Show the browser window.
- `--include-best-practice`
  Also check axe-core's best-practice rules.
- `--ai-model TEXT`
  Claude model for the AI tiers. Default: claude-sonnet-5.
- `--ai-engine [auto|api|claude-code]`
  API key, Claude subscription, or your choice in setup. Default: auto.
- `--scans-dir PATH`
  Save this scan here instead of your scans folder (`magnacoda-scans` in Documents, unless preferences.ini says otherwise).

For more about each option, type `docs advanced`.

## examples

### Example options (when launching):

- `magnacoda --help`
  Show the help without starting the shell.

### Example commands (in the shell):

- `scan https://example.com`
  Scan a page (from outside the shell, start with `magnacoda`).
- `help`
  Browse all of the help, one screen at a time. You can type `help scan`, and it will open at the scan section.
- `setup`
  Install Chromium and save your Anthropic API key (one-time).
- `setup --forget-key`
  Delete the saved Anthropic API key.

### Example scans (inside the shell, leave out `magnacoda`):

- `magnacoda scan https://example.com --screen both`
  Test the page on a desktop screen and a phone.
- `magnacoda scan https://example.com -o results.json --fail-on serious`
  Machine-readable output for CI; fails the build on serious+ issues.
- `magnacoda scan https://example.com --ai explain`
  Plain-language explanations for the top 10 findings (needs your own Anthropic API key, or Claude Code).
- `magnacoda scan https://example.com --storage-state login.json`
  Scan a page behind a login, from a saved Playwright login session.

## add-ons

### Add-ons

An add-on is a separate Python package that adds to *magnacoda*: new commands, help sections, settings, or a choice at the start of the wizard. *magnacoda* comes with one, favorites, which saves the scans you run often. Others can be installed alongside it.

Anyone can write an add-on, so they vary in quality and in how they're written. *magnacoda* makes it clear when content comes from an add-on:

- The shell's banner lists their commands on a line of their own, "Add-on commands."
- In this help, their sections come after *magnacoda*'s own. Each is marked "(add-on)" in the section list (press `g`), with a line under its title naming the add-on, its version and its author.
- The about screen (`about`) lists every add-on in use, with its version and its commands.
- When you update *magnacoda* (`update`), add-ons published on PyPI are updated with it.

To install an add-on, add it to the same install as *magnacoda*: with uv, `uv tool install magnacoda --with NAME`, or with pipx, `pipx inject magnacoda NAME`.

### Make it do more: write an add-on

If you'd like *magnacoda* to do something it doesn't, write an add-on. Changes to *magnacoda*'s own code would have to be redone for every new version, but an add-on is a package of its own. It stays installed when you update *magnacoda*, and you can share it with others or publish it on PyPI.

Anyone can build one. An add-on is a small Python package with one file of hooks, and the simplest example rings the terminal's bell when a scan finishes. The guide, with that example and the rest, is "Writing an add-on" in the contributing guide, at https://magnacoda.dev/add-ons

## more info

### Where to find more

- `readme`, `readme NAME`
  The README: installing, the wizard, the shell and the help viewer.
- `docs`, `docs NAME`
  The manual, in this same viewer: every option and feature, settings, CI setup, and how *magnacoda* compares with other tools. Start at a section by naming it (docs ci), or press `g` for its contents.
- `news`
  What's new in your version, and news about *magnacoda*.
- `about`
  The website and repository addresses, the author, the license and your add-ons.

The website is magnacoda.dev.

## about the name

### About the name

*magna* is Latin for "great," and a *coda* is the passage that brings a piece of music to its close. Accessibility is part of what makes code finished, and great: *magnacoda*.
