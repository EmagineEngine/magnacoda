"""Local server for the review page; saves ticks back into the checklist (ticks.py).

127.0.0.1 only, on a free port, with a random token in every URL. Requests without the token, for
another Host, or with a foreign Origin are refused. Serves only the page and the scan's screenshots.
"""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from magnacoda import recheck, review_page, ticks
from magnacoda.review_page import Variant

_MAX_BODY = 10_000
TELL_PAGES_SECONDS = 2.0  # at most this long for the open pages to hear "stopped" before shutting down
_PING_SECONDS = 15.0  # a comment line now and then, so a closed tab's connection is noticed


class ReviewServer:
    """One review session: start(), the page's address in `url`, then wait() until Done or Ctrl+C."""

    def __init__(self, folder: Path, variants: list[Variant]) -> None:
        self.folder = folder.resolve()
        self.variants = variants
        self.token = secrets.token_urlsafe(18)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/{self.token}/"
        self._stopped = threading.Event()
        self._ending = threading.Event()  # set first, so the open pages hear "stopped"
        self._listening = threading.Condition()
        self._listeners = 0  # pages with an open events connection
        self._rechecking = threading.Lock()  # one recheck at a time

    def start(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wait(self) -> bool:
        """Block until the page's Done button (or stop()); Ctrl+C also ends it. Whether it was Ctrl+C."""
        try:
            while not self._stopped.wait(0.25):
                pass
        except KeyboardInterrupt:
            return True
        finally:
            self.stop()
        return False

    def stop(self) -> None:
        """Tell the open pages first (they show their Done view), then shut down, so the terminal only
        says the review has ended once the browser shows it too."""
        if not self._stopped.is_set():
            self._ending.set()
            with self._listening:
                self._listening.wait_for(lambda: self._listeners == 0, timeout=TELL_PAGES_SECONDS)
            self._stopped.set()
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()
        self.httpd.server_close()

    def _events(self, handler: BaseHTTPRequestHandler) -> None:
        """A page's events connection (server-sent events): held open until the review stops, then
        "stopped"."""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        with self._listening:
            self._listeners += 1
        try:
            while not self._ending.wait(_PING_SECONDS):
                handler.wfile.write(b": still here\n\n")
                handler.wfile.flush()
            handler.wfile.write(b"event: stopped\ndata: \n\n")
            handler.wfile.flush()
        except OSError:
            pass  # the tab was closed
        finally:
            handler.close_connection = True
            with self._listening:
                self._listeners -= 1
                self._listening.notify_all()

    def variant(self, label: str | None) -> Variant:
        return next((v for v in self.variants if v.label == label), self.variants[0])

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - quiet
                pass

            def _allowed(self) -> str | None:
                """The part of the path after the token, or None (and a refusal sent) if not allowed."""
                if self.headers.get("Host") != f"127.0.0.1:{server.port}":
                    self._send(403, "text/plain", b"Forbidden")
                    return None
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://127.0.0.1:{server.port}":
                    self._send(403, "text/plain", b"Forbidden")
                    return None
                path = urlsplit(self.path).path
                prefix = f"/{server.token}/"
                if not path.startswith(prefix):
                    self._send(404, "text/plain", b"Not found")
                    return None
                return path[len(prefix) :]

            def _send(self, code: int, kind: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                if kind.startswith("text/html"):
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; "
                        "base-uri 'none'; frame-ancestors 'none'",
                    )
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - http.server's naming
                rest = self._allowed()
                if rest is None:
                    return
                if rest == "":
                    query = parse_qs(urlsplit(self.path).query)
                    current = server.variant(query.get("variant", [""])[0])
                    body = review_page.page(server.variants, current).encode("utf-8")
                    self._send(200, "text/html; charset=utf-8", body)
                elif rest == "events":
                    server._events(self)
                elif rest.startswith("images/"):
                    self._image(rest)
                else:
                    self._send(404, "text/plain", b"Not found")

            def _image(self, rest: str) -> None:
                images = (server.folder / "images").resolve()
                target = (server.folder / rest).resolve()
                # Only a PNG directly inside this scan's images folder: no other file, no ../ tricks.
                if target.parent != images or target.suffix != ".png" or not target.is_file():
                    self._send(404, "text/plain", b"Not found")
                    return
                self._send(200, "image/png", target.read_bytes())

            def do_POST(self) -> None:  # noqa: N802
                rest = self._allowed()
                if rest is None:
                    return
                if rest == "done":
                    self._send(200, "text/html; charset=utf-8", _DONE_PAGE)
                    server.stop()
                    return
                if rest == "recheck":
                    self._recheck()
                    return
                if rest != "tick" or self.headers.get("Content-Type") != "application/json":
                    self._send(404, "text/plain", b"Not found")
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    data = json.loads(self.rfile.read(min(length, _MAX_BODY)))
                    variant = server.variant(data.get("variant"))
                    ticks.set_tick(variant.checklist, str(data["id"]), bool(data["checked"]), variant.results)
                except (ValueError, KeyError, TypeError, ticks.UnknownItem, OSError):
                    self._send(400, "text/plain", b"Could not save")
                    return
                self._send(204, "text/plain", b"")

            def _recheck(self) -> None:
                """Test the Fix items again (recheck.py), updating the saved files; the page then reloads."""
                if not server._rechecking.acquire(blocking=False):
                    self._send(409, "text/plain", b"A recheck is already running")
                    return
                try:
                    result = recheck.recheck_scan(server.variants)
                except Exception as exc:  # noqa: BLE001 - say so on the page, never crash the server
                    body = {"summary": "", "errors": [str(exc).splitlines()[0] if str(exc) else "error"]}
                else:
                    errors = [f"{v.label or 'this scan'}: {v.error}" for v in result.variants if v.error]
                    body = {"summary": result.summary(), "errors": errors}
                finally:
                    server._rechecking.release()
                self._send(200, "application/json", json.dumps(body).encode("utf-8"))

        return Handler


_DONE_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Done</title>'
    "<style>.logo { height: 2rem; width: auto; }</style></head>"
    f"<body><main>{review_page.logo()}<h1>Done</h1><p>magnacoda has stopped showing this scan. "
    "You can close this tab.</p></main></body></html>"
).encode()
