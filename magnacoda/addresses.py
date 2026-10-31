"""Turn what the user typed into a full URL.

- A URL with a scheme is used as is.
- Local addresses get http:// (dev servers rarely have https): localhost, .local/.test/.internal and
  similar, private IPs, and one-word names with a port.
- A bare number isn't an address (NotAnAddress); it's usually an answer typed at the wrong prompt.
- A bare word is resolved like the browser would; if it doesn't resolve, it's probably a mistyped
  command (NotAnAddress).
- Anything else gets https:// (the scan falls back to http:// once if that can't connect).
"""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

_HAS_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_NUMBERS_ONLY = re.compile(r"^[0-9.]+$")
_LOCAL_SUFFIXES = (".localhost", ".local", ".test", ".internal", ".lan", ".home.arpa")
LOOKUP_TIMEOUT = 2.0  # seconds to wait for a one-word name to be found


class NotAnAddress(ValueError):
    """The text is neither a command nor something that can be scanned."""


@dataclass(frozen=True)
class Address:
    url: str
    added: str | None = None  # "https" or "http" when magnacoda added it; None when it was typed


def resolves(host: str, timeout: float = LOOKUP_TIMEOUT) -> bool:
    """Whether the name resolves (DNS or hosts file). Separate from look_up so tests can stub it."""
    return look_up(host, timeout)


def look_up(host: str, timeout: float) -> bool:
    found: list[bool] = []

    def attempt() -> None:
        try:
            socket.getaddrinfo(host, None)
            found.append(True)
        except (OSError, UnicodeError):
            found.append(False)

    thread = threading.Thread(target=attempt, daemon=True)
    thread.start()
    thread.join(timeout)
    return bool(found and found[0])


def _is_local_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def interpret(text: str, resolve: Callable[[str], bool] | None = None) -> Address:
    """The full address for what was typed (see the module docstring). Raises NotAnAddress."""
    text = text.strip()
    if _HAS_SCHEME.match(text):
        return Address(text)
    try:
        parts = urlsplit("//" + text)
        host, port = parts.hostname, parts.port
    except ValueError as exc:  # a port that isn't a number, a broken [IPv6] address
        raise NotAnAddress(text) from exc
    if not host:
        raise NotAnAddress(text)
    if _NUMBERS_ONLY.match(host) and not _is_ip(host):
        # 1, 42 or 10.1 would be looked up as old IP shorthand (1 = 0.0.0.1), and then scanned. A bare
        # number typed in the shell is far more likely an answer to a list that wasn't asking.
        raise NotAnAddress(text)
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or _is_local_ip(host):
        return Address("http://" + text, "http")
    if "." in host or _is_ip(host):
        return Address("https://" + text, "https")
    if port is not None or (resolve or resolves)(host):
        return Address("http://" + text, "http")
    raise NotAnAddress(text)


def as_http(url: str) -> str:
    """The same address over plain http (for the fallback when https can't connect)."""
    return "http://" + url.removeprefix("https://")
