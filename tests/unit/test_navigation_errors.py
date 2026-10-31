from magnacoda.browser.launcher import describe_navigation_error

CALL_LOG = (
    "Page.goto: net::{code} at https://x/\nCall log:\n"
    '  - navigating to "https://x/", waiting until "domcontentloaded"\n'
)


def _describe(raw: str, url: str = "https://conversation-hog") -> str:
    return describe_navigation_error(Exception(raw), url, 30_000)


def test_unresolvable_host_is_short_and_actionable():
    message = _describe(CALL_LOG.format(code="ERR_NAME_NOT_RESOLVED"))
    assert "resolve the host name 'conversation-hog'" in message
    assert "Call log" not in message and "domcontentloaded" not in message


def test_connection_refused():
    assert "connection refused" in _describe(CALL_LOG.format(code="ERR_CONNECTION_REFUSED"))


def test_certificate_error_points_at_the_bypass_flag():
    assert "--ignore-https-errors" in _describe(CALL_LOG.format(code="ERR_CERT_AUTHORITY_INVALID"))


def test_timeout_mentions_the_flag_and_seconds():
    message = _describe("Page.goto: Timeout 30000ms exceeded.\nCall log:\n  - navigating")
    assert "30s" in message and "--wait 30" in message


def test_missing_scheme_suggests_https():
    message = _describe("Page.goto: Cannot navigate to invalid URL\nCall log:", url="example.com")
    assert "https://example.com" in message


def test_unknown_error_falls_back_to_first_line_only():
    message = _describe("Page.goto: something odd\nCall log:\n  - noise")
    assert message.endswith("something odd") and "noise" not in message
