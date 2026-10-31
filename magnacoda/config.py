from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from magnacoda import preferences
from magnacoda.credentials import load_stored_key
from magnacoda.findings.models import WcagLevel

AITier = Literal["off", "explain", "semantic"]
AIEngine = Literal["auto", "api", "claude-code"]
FixesTier = Literal["off", "template", "ai"]
WcagVersion = Literal["2.0", "2.1", "2.2"]
BrowserName = Literal["chromium", "firefox", "webkit"]
ColorScheme = Literal["light", "dark"]
Screen = Literal["desktop", "mobile"]
FailOn = Literal["none", "minor", "moderate", "serious", "critical"]


class StabilityConfig(BaseModel):
    wait_for_selector: str | None = None
    quiet_period_ms: int = 500
    min_wait_ms: int = 500
    stability_timeout_ms: int = 30_000
    extra_wait_ms: int = 0
    nav_timeout_ms: int = 30_000


class AIConfig(BaseModel):
    tier: AITier = "off"
    model: str = "claude-sonnet-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    assume_yes: bool = False
    # How the AI calls run: "api" (an Anthropic API key), "claude-code" (the user's Claude Code login,
    # through `claude -p`, so a Claude subscription can be used), or "auto" (see resolve_engine).
    engine: AIEngine = "auto"

    def resolve_api_key(self) -> str | None:
        """The env var if set, else a key saved by `setup`."""
        return os.environ.get(self.api_key_env) or load_stored_key(self.api_key_env)

    def resolve_engine(self) -> Literal["api", "claude-code"]:
        """--ai-engine, else the saved choice. Never the Claude plan without the user's yes; the API
        is the fallback, and its missing-key error explains both options."""
        if self.engine != "auto":
            return self.engine
        choice = preferences.load().ai_engine
        return "api" if choice == "ask" else choice

    def claude_plan_undecided(self) -> bool:
        """Claude Code is available but the user hasn't chosen an engine yet."""
        return (
            self.engine == "auto" and bool(shutil.which("claude")) and preferences.load().ai_engine == "ask"
        )


class ScanConfig(BaseModel):
    url: str
    ai: AIConfig = Field(default_factory=AIConfig)
    fixes_tier: FixesTier = "template"
    wcag_version: WcagVersion = "2.2"
    level: WcagLevel = "AA"
    include_best_practice: bool = False

    output_path: Path | None = None
    fail_on: FailOn = "serious"
    verbosity: int = 0
    no_color: bool = False

    browser_name: BrowserName = "chromium"
    headless: bool = True
    # None = not chosen: the launcher then uses the device's own size, or 1280x720 with no device.
    viewport_width: int | None = None
    viewport_height: int | None = None
    device: str | None = None
    screen: Screen | None = None
    color_scheme: ColorScheme | None = None
    # Screenshots of the page's images, for the Markdown checklist (browser/images.py). Set when a
    # checklist is being written; a scan shown only on screen skips them and stays as fast as before.
    capture_images: bool = False
    # --quick: skip the slowest interaction tests (motion, hover, clicks, single keys).
    quick: bool = False
    user_agent: str | None = None
    extra_http_headers: dict[str, str] = Field(default_factory=dict)
    cookies: list[dict[str, str]] = Field(default_factory=list)  # name, value, url
    storage_state: Path | None = None
    ignore_https_errors: bool = False

    stability: StabilityConfig = Field(default_factory=StabilityConfig)
