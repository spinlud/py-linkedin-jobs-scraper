"""A local TLS server answering as www.linkedin.com, for an account signed in with SESSION."""

from __future__ import annotations

import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

from . import pages

SESSION = 'fake-session'


class Request(NamedTuple):
    path: str
    headers: dict[str, str]


class FakeLinkedin:
    def __init__(self, certificate: Path) -> None:
        fake = self
        self.requests: list[Request] = []
        # Ids of the jobs whose details are refused the first time they are asked for
        self.throttled_once: set[str] = set()

        class Handler(BaseHTTPRequestHandler):
            # Ends the connections Chrome opens ahead of need and never uses
            timeout = 5

            def do_GET(self) -> None:
                fake._answer(self)

            def log_message(self, *_args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port: int = self._server.server_address[1]
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate)
        # Each connection is negotiated in its own thread, so an idle one holds up no other
        self._server.socket = context.wrap_socket(
            self._server.socket, server_side=True, do_handshake_on_connect=False
        )

    @property
    def requested(self) -> list[str]:
        return [request.path for request in self.requests]

    @contextmanager
    def serving(self) -> Iterator[FakeLinkedin]:
        thread = threading.Thread(target=self._server.serve_forever, args=(0.05,))
        thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            thread.join()
            self._server.server_close()

    def _answer(self, handler: BaseHTTPRequestHandler) -> None:
        self.requests.append(Request(handler.path, dict(handler.headers.items())))
        status, parts = self._page(handler.path, handler.headers.get('Cookie', ''))

        try:
            handler.send_response(status)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            for index, part in enumerate(parts):
                if index:
                    sleep(0.7)
                handler.wfile.write(part.encode())
        except OSError:
            # The browser left the page before the end of it
            pass

    def _page(self, url: str, cookie: str) -> tuple[int, tuple[str, ...]]:
        """The status and the parts of the page, which is streamed in one part after the other"""
        path = urlsplit(url).path
        query = parse_qs(urlsplit(url).query)

        if path == '/':
            return 200, (pages.HOME,)

        session = SimpleCookie(cookie).get('li_at')
        if session is None or session.value != SESSION:
            return 200, (pages.SIGNED_OUT,)

        if path == '/jobs/search-results/' and query.get('start') == ['0']:
            return 200, pages.SEARCH

        job_id = ''.join(filter(str.isdigit, path))

        if path == f'/jobs/view/{job_id}/':
            return 200, (pages.single_job(job_id),)

        if path == f'{pages.DETAILS_PATH}{job_id}' and job_id in pages.JOBS:
            if job_id in self.throttled_once:
                self.throttled_once.remove(job_id)
                return 429, ()
            return 200, (pages.job_details(job_id),)

        return 404, ()
