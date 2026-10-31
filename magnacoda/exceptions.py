class MagnacodaError(Exception):
    """Base class for all magnacoda errors."""


class NavigationError(MagnacodaError):
    """The page couldn't be loaded or used. `could_not_connect`: refused/reset/TLS, so http may work."""

    def __init__(self, message: str, *, could_not_connect: bool = False) -> None:
        super().__init__(message)
        self.could_not_connect = could_not_connect


class BrowserNotInstalledError(MagnacodaError):
    """Playwright browser binaries are missing; run `magnacoda setup`."""


class AxeInjectionError(MagnacodaError):
    """axe-core failed to load or run in the page."""


class AIConfigError(MagnacodaError):
    """An AI tier was requested but is misconfigured (missing key, missing extra)."""


class AIAuthenticationError(MagnacodaError):
    """The Anthropic API rejected the configured key (invalid, revoked, or expired)."""


class ConsentDeclinedError(MagnacodaError):
    """The user declined (or could not be asked for) AI data-sharing consent."""
