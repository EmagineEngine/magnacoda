from __future__ import annotations

import sys

from magnacoda import questions
from magnacoda.config import AIConfig
from magnacoda.exceptions import ConsentDeclinedError

_TIER_DESCRIPTIONS = {
    "explain": (
        "the rule id, WCAG criterion, selector, and a truncated HTML snippet for the top 10 findings only"
    ),
    "semantic": (
        "the same top-10 data as 'explain', plus a bounded DOM extract (images' alt text and "
        "file names, the heading outline, link text and context) used to look for issues axe-core can't "
        "detect mechanically"
    ),
}


def confirm_ai_usage(ai: AIConfig, passes: int = 1) -> None:
    """Print a one-time data-sharing banner and require explicit consent before any AI call."""
    if ai.tier == "off":
        return

    description = _TIER_DESCRIPTIONS[ai.tier]
    if ai.resolve_engine() == "claude-code":
        banner = (
            f"\n--ai={ai.tier} will send {description} to Anthropic through your Claude Code login "
            f"(model: {ai.model}). Your Claude plan's terms and data settings apply, which can differ "
            "from the API's (for example, whether conversations may be used to improve Claude).\n"
            "No full-page HTML or screenshots are ever sent.\n"
        )
    else:
        banner = (
            f"\n--ai={ai.tier} will send {description} to Anthropic's API "
            f"(model: {ai.model}) using the key in ${ai.api_key_env}.\n"
            "No full-page HTML or screenshots are ever sent.\n"
        )
    if passes > 1:
        banner += (
            f"This data is sent once per scan, and {passes} scans will run "
            "(one per screen size and color scheme you chose).\n"
        )
    if ai.assume_yes:
        print(banner, file=sys.stderr)
        return

    if not sys.stdin.isatty():
        raise ConsentDeclinedError(
            "AI tier requested in a non-interactive session without --yes; refusing to "
            "send data without explicit consent."
        )

    # The same spacing as every other question (see questions.py): the explanation just above it.
    if not questions.ask_yes_no("Continue?", intro=banner.strip("\n"), default=False, err=True):
        raise ConsentDeclinedError("User declined the AI data-sharing consent prompt.")
