# What's new in *magnacoda*

<!--
The notes shown by `news` (section "whats-new") for the version that is installed, and announced once on the shell banner after someone upgrades ("what's new in 0.4.0 - type news"). A first install isn't announced.

HOW IT IS READ
  * Anything inside an HTML comment, like this one, is a note to editors. It is never shown.
  * "## X.Y.Z" starts the notes for that release (text after the number, such as a date, is ignored). Add a section, newest first, before tagging each release; a version without a section shows no notes and isn't announced.
  * Write for people who use *magnacoda*, not for developers: what they can do now, in plain words, one long line per paragraph. Terms and lists work as in help.md.
  * Keep each entry to one short sentence, two at most. Leave the details to the manual and help.
-->

## 0.1.7

- The docs are easier to use. The guide to writing add-ons is its own document, `view add-ons.md`, and `view contributing.md` is shorter.

## 0.1.6

- On Windows, the shortcut opens Windows Terminal. Remake it with `shortcut remove`, then `shortcut`.
- The help viewer now shows its full colors and code shading on Windows.
- The classic Windows console shows ticks as `[x]`, since its fonts lack `✓`.

## 0.1.5

- `menu`
  Lists the commands. `clear` starts a fresh page.
- A short welcome replaces the title screen.
- Blank lines set off each command's output.
- Enter cancels at numbered lists.
- Stopping a review ends its browser page too.
- Mac shortcuts open one window and close it after.
- Colors show on Windows too.
- Setup offers a shortcut even when you skip Chromium.

## 0.1.4

- `news`
  Numbered, starting with what's new in a newer version. Type a number to read an item.
- `uninstall`
  Removes *magnacoda* and its shortcuts, and asks before deleting your settings, Chromium or scans.
- News and updates show on the title screen, and `update` shows what's new before installing.
- In a section list (`g`), the arrows go on from what your typing highlights.

## 0.1.3

- `--title`
  Shows the title screen. Set how often with `title` in preferences.
- The review page shows the *magnacoda* logo.
- An option typed alone in the shell no longer opens a second shell.

## 0.1.2

Getting started is smoother, and *magnacoda*'s AI works better alongside your AI coding agent.

- `setup`
  Offered the first time you open *magnacoda*, and it then offers to start the wizard.
- `--ai semantic`
  The AI reads your page more like a screen reader does, so it raises fewer false alarms.
- `recheck FOLDER`
  Rechecks one scan straight away. Scripts and AI agents get three rechecks before handing over to you.
- `docs full example`
  One round of work with your AI coding agent and *magnacoda*'s AI, from scan to review.
- `view CONTRIBUTING.md`
  The guide to contributing and add-ons now comes with *magnacoda*.
- Images hidden from screen readers no longer show up as missing their text alternative.
- Code examples in numbered steps stay in their step, closer to the left edge.

## 0.1.1

A small update that makes updating easier.

- `update`
  If you installed *magnacoda* with uv, `update` now upgrades it for you, along with any add-ons, instead of showing a command to run yourself. It still asks first.

## 0.1.0

The first public release of *magnacoda*: scan a web page for WCAG 2 accessibility issues in a real browser, with plain-language explanations and fix suggestions.

- `wizard`
  Let the wizard build your scan: it asks a few questions, then shows the command it made.
- `favorites`
  See the scans you saved from the wizard, restart one from its first question, or delete the ones you no longer need.
- `help`
  Read all of the help, one screen at a time: press `g` to go to a section, `o` to open another document, or `/` to find a word.
- `news`
  Check for updates, read these notes, and see the news about *magnacoda*.
- `screenreader on`, `screenreader off`
  Choose how *magnacoda* shows text. With `screenreader on`, text appears at once, a plain line replaces the spinner during a scan, and help prints as a single page. With `screenreader off`, text flows down the page, a spinner shows a scan's progress, and help comes one page at a time.
- `shortcut`
  Install shortcuts to open *magnacoda* from your app menu or Start menu, or from your desktop.
- `readme`, `docs`
  Read the README and the full manual, one section at a time, without leaving *magnacoda*.
