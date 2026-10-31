"""Turning what people type into the address to scan (addresses.py)."""

import pytest

from magnacoda import addresses
from magnacoda.addresses import Address, NotAnAddress, interpret


@pytest.mark.parametrize(
    ("typed", "url"),
    [
        ("https://example.com", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("file:///home/me/page.html", "file:///home/me/page.html"),
    ],
)
def test_a_full_address_is_used_as_typed(typed, url):
    assert interpret(typed) == Address(url, None)


@pytest.mark.parametrize("typed", ["example.com", "www.example.com/about?x=1", "example.com:8443", "8.8.8.8"])
def test_a_web_address_gets_https(typed):
    assert interpret(typed) == Address("https://" + typed, "https")


@pytest.mark.parametrize(
    "typed",
    [
        "localhost",
        "localhost:3000",
        "127.0.0.1:8080",
        "[::1]:8000",
        "192.168.1.20",
        "10.0.0.5/admin",
        "mysite.test",
        "app.localhost:5173",
        "printer.local",
        "mysite:8080",
    ],
)
def test_a_local_address_gets_http(typed):
    assert interpret(typed) == Address("http://" + typed, "http")


def test_a_one_word_name_is_scanned_over_http_only_if_that_computer_exists():
    assert interpret("mysite", resolve=lambda host: True) == Address("http://mysite", "http")
    with pytest.raises(NotAnAddress):
        interpret("overview", resolve=lambda host: False)


@pytest.mark.parametrize("typed", ["", "   ", "mysite:port", "[::1"])
def test_nothing_or_a_broken_address_is_not_an_address(typed):
    with pytest.raises(NotAnAddress):
        interpret(typed, resolve=lambda host: True)


def test_the_http_fallback_keeps_everything_but_the_scheme():
    assert addresses.as_http("https://example.com/a?b=1") == "http://example.com/a?b=1"


def test_looking_up_a_name_finds_localhost_and_gives_up_after_the_timeout(monkeypatch):
    import socket
    import time

    assert addresses.look_up("localhost", 2.0)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: time.sleep(3))
    start = time.monotonic()
    assert not addresses.look_up("slowname", 0.2)
    assert time.monotonic() - start < 1


@pytest.mark.parametrize("typed", ["1", "42", "10.1", "1.2.3"])
def test_a_bare_number_is_not_an_address_even_though_it_would_resolve(typed):
    with pytest.raises(NotAnAddress):
        interpret(typed, resolve=lambda host: True)  # 1 really resolves, to 0.0.0.1
