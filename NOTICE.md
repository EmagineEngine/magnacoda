# Third-Party Notices

This project is licensed under the Functional Source License, Version 1.1, MIT Future License (FSL-1.1-MIT; see `LICENSE.md`): each version also becomes available under the MIT License two years after it is published.

It vendors one third-party component unmodified:

## axe-core

- **Location**: `magnacoda/vendor/axe-core/axe.min.js`
- **Upstream**: https://github.com/dequelabs/axe-core
- **License**: Mozilla Public License 2.0 (MPL-2.0) — see `magnacoda/vendor/axe-core/LICENSE`
- **Version**: see `magnacoda/vendor/axe-core/VERSION`

The MPL-2.0 applies only to the vendored `axe.min.js` file itself. It is distributed unmodified; the MPL-2.0 header inside the file is preserved.

## WCAG 2.2 criteria data

- **Location**: `magnacoda/data/wcag_criteria.json`
- **Source**: the W3C's machine-readable WCAG 2.2 (https://www.w3.org/WAI/WCAG22/wcag.json), reduced to criterion numbers, titles, levels, versions and links to the W3C's Understanding pages. Regenerate with `scripts/update_wcag_criteria.py`.
- **Copyright**: (c) W3C (MIT, ERCIM, Keio, Beihang). WCAG is published under the W3C Document License; see https://www.w3.org/copyright/document-license/.

`magnacoda/data/criteria_guidance.json` (the "how to check" text and page-feature triggers) is original to this project, written for *magnacoda*.

## Software installed alongside *magnacoda* (not vendored)

These are declared as dependencies and installed separately by pip or pipx; none of their code is copied into this repository. Licenses as published by each project (checked against the installed package metadata):

| Package | Role | License |
|---|---|---|
| Playwright (Microsoft) | Drives the browser | Apache-2.0 |
| Click (Pallets) | Command line | BSD-3-Clause |
| Rich (Will McGugan / Textualize) | Terminal output | MIT |
| Pydantic | Data models | MIT |
| anthropic (Anthropic) | Claude API client | MIT |
| markdown-it-py (Executable Books) | Turns the checklist into HTML for the review page | MIT |
| packaging (Python Packaging Authority) | Compares version numbers for the update check | Apache-2.0 OR BSD-2-Clause |
| sourcemap (Matt Robenolt) | Reads CSS source maps | BSD-2-Clause |
| platformdirs (tox-dev) | Finds the Documents folder | MIT |
| pyshortcuts (Matthew Newville) | Menu and desktop shortcuts | MIT |
| certifi (Kenneth Reitz) | The certificates HTTPS connections trust | MPL-2.0 |
| pywin32 (Mark Hammond), on Windows only | Sets the Start menu shortcut's key | PSF-2.0 |

Playwright downloads its own builds of Chromium and Firefox when you run `magnacoda setup` or `playwright install`. Those browsers are not distributed with *magnacoda* and remain under their own licenses.

## Affiliation and trademarks

*magnacoda* is an independent project. It is not affiliated with, endorsed by, or sponsored by the W3C or the WCAG working groups, Deque Systems, Microsoft, Google, Mozilla or Anthropic. "WCAG," "W3C," "axe," "Playwright," "Chromium," "Firefox" and "Claude" are names or trademarks of their respective owners and are used only to identify the software and standards this tool works with. A clean *magnacoda* report is not a certification of WCAG conformance or of legal compliance.
