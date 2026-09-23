"""Watch Jev race across Wikipedia: uv run server.py, then open http://localhost:8000

The page sends a start and a target to /race, which streams each of Jev's clicks as
Server-Sent Events. The server listens on localhost only, because it spends the TypeSafe
key and your Wikipedia contact from .env.
"""

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from race import race

ROOT = Path(__file__).parent
PAGE = ROOT / "index.html"
DECIDE = ROOT / "decide.py"
PORT = 8000

_decide = {"mtime": None, "module": None}


def load_decide():
    """Import decide.py, again whenever the file changes, so edits apply without restarting the server.

    Between edits the module is reused, which keeps its TypeSafe connection warm.
    """
    mtime = DECIDE.stat().st_mtime
    if _decide["mtime"] != mtime:
        spec = importlib.util.spec_from_file_location("decide", DECIDE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _decide.update(mtime=mtime, module=module)
    return _decide["module"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0].strip() for key, values in parse_qs(url.query).items()}
        if url.path == "/":
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/race":
            self.stream_race(query.get("start", ""), query.get("target", ""))
        else:
            self.send_error(404)

    def stream_race(self, start: str, target: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            if not start or not target:
                raise ValueError("Enter both a starting page and a target.")
            for event in race(start, target, load_decide().choose_link):
                self.send_event(event)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page was closed or a new race started
        except Exception as error:
            self.send_event({"type": "error", "message": str(error) or type(error).__name__})

    def send_event(self, event: dict):
        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.flush()


if __name__ == "__main__":
    print(f"Open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
