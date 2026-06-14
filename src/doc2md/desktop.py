"""doc2md reader desktop app — PyWebView + http.server."""

from __future__ import annotations

import http.server
import socket
import threading
from pathlib import Path

import webview

_ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def _make_handler(root: Path):
    class _Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    # directory kwarg routes all requests relative to root
    import functools
    return functools.partial(_Handler, directory=str(root))


def _start_server(port: int) -> None:
    httpd = http.server.HTTPServer(('localhost', port), _make_handler(_ROOT))
    httpd.serve_forever()


def main() -> None:
    port = _free_port()
    threading.Thread(target=_start_server, args=(port,), daemon=True).start()
    webview.create_window(
        'doc2md Reader',
        f'http://localhost:{port}/reader/index.html',
        width=1400,
        height=900,
        min_size=(800, 600),
    )
    webview.start()


if __name__ == '__main__':
    main()
