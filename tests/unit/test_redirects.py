"""Redirects (browser/redirects.py): which addresses are the same site, and the quick check before a scan."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from magnacoda.browser import redirects


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("https://example.org", "https://example.org/blog", True),
        ("http://example.org", "https://www.example.org/", True),  # http and https, www. or not
        ("https://example.com", "https://example.org", False),
        ("https://example.com", "https://shop.example.com", False),  # another subdomain is another site
        ("http://localhost:3000", "http://localhost:4000", False),  # another port too
        ("https://example.com:443", "https://example.com", True),  # the usual port is the same as none
    ],
)
def test_which_addresses_are_the_same_site(a, b, same):
    assert redirects.same_site(a, b) is same


def test_reached_from_is_only_said_for_another_site():
    assert redirects.from_elsewhere("https://example.org/", "https://example.com") == "https://example.com"
    assert redirects.from_elsewhere("https://example.org/", "http://example.org") is None
    assert redirects.from_elsewhere("https://example.org/", None) is None
    assert redirects.host("https://WWW.Example.org/x") == "example.org"


@pytest.fixture
def redirecting_server():
    """Answers /old with a 301 to the same server under another name (localhost): another site."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the name http.server calls
            if self.path == "/old":
                self.send_response(301)
                self.send_header("Location", f"http://localhost:{self.server.server_address[1]}/new")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_the_quick_check_follows_the_servers_redirects(redirecting_server):
    port = redirecting_server.rsplit(":", 1)[1]
    assert redirects.check_address(f"{redirecting_server}/old") == f"http://localhost:{port}/new"
    assert redirects.check_address(f"{redirecting_server}/new") == f"{redirecting_server}/new"


def test_the_quick_check_says_nothing_when_it_cant_tell():
    assert redirects.check_address("http://127.0.0.1:9/") is None  # nothing listens there
    assert redirects.check_address("file:///tmp/page.html") is None
