from __future__ import annotations

from importlib import metadata

from magnacoda import __version__, plugins


def _field(md: metadata.PackageMetadata, name: str) -> str:
    return md[name] if name in md else ""


def _project_urls(md: metadata.PackageMetadata) -> dict[str, str]:
    urls = {}
    for entry in md.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip()] = url.strip()
    return urls


def _addons_row() -> str:
    """Bundled add-ons first, then one entry per installed package: "pkg 1.0 (add-ons: a, b; commands: c)"."""
    commands_by = plugins.added_commands()
    entries = []
    by_package: dict[str, list[plugins.Plugin]] = {}
    for addon in plugins.loaded():
        if addon.bundled:
            commands = commands_by.get(addon.label)
            entries.append(
                f"{addon.name} (built in{'; commands: ' + ', '.join(commands) if commands else ''})"
            )
        else:
            by_package.setdefault(addon.package, []).append(addon)
    for package, parts in by_package.items():
        details = []
        if len(parts) > 1:
            details.append("add-ons: " + ", ".join(part.name for part in parts))
        commands = commands_by.get(package)
        if commands:
            details.append("commands: " + ", ".join(commands))
        listed = f" ({'; '.join(details)})" if details else ""
        entries.append(f"{package} {parts[0].version}{listed}")
    return ", ".join(entries)


# As in the notice in LICENSE.md: the owner, which isn't the same as the author shown above.
COPYRIGHT = "2026 Phillip E. Honstein dba EmagineEngine.com"


def about_text() -> str:
    """The `about` screen. Author, links and license come from the package metadata."""
    from magnacoda.browser.axe_injector import axe_core_version

    try:
        md = metadata.metadata("magnacoda")
        summary = _field(md, "Summary")
        author = _field(md, "Author")
        license_name = _field(md, "License-Expression") or _field(md, "License")
        urls = _project_urls(md)
    except metadata.PackageNotFoundError:  # running from a source tree that isn't installed
        summary = author = license_name = ""
        urls = {}

    rows = [
        ("Author", author),
        ("Copyright", f"© {COPYRIGHT}"),
        ("Website", urls.get("Website", "")),
        ("Repository", urls.get("Repository") or urls.get("Homepage", "")),
        ("Issues", urls.get("Issues", "")),
        ("License", f"{license_name} (see LICENSE.md)" if license_name else ""),
        ("axe-core", f"{axe_core_version()} (the rule engine that does the detection)"),
        ("News", "type news for updates and news about a11y and magnacoda"),
        ("Add-ons", _addons_row()),
    ]
    width = max(len(label) for label, _ in rows) + 2
    lines = ["", f"{plugins.edition().display_name} {__version__}", ""]
    if summary:
        lines += [summary, ""]
    lines += [f"{(label + ':').ljust(width)}{value}" for label, value in rows if value]
    lines += [
        "",
        "magnacoda is an independent project, not affiliated with or endorsed by the W3C, the WCAG "
        "working groups, Deque Systems, Microsoft, Google, Mozilla or Anthropic. See the credits and "
        "disclaimer in the README (the readme command shows it).",
    ]
    return "\n".join(lines)
