"""Play Wikipedia races in the browser: uv run server.py, then open http://localhost:8000

Players race by hand first. Copying decide.py into this folder unlocks "Play with Jev",
which streams Jev's clicks as Server-Sent Events. The server listens on localhost only,
because it spends the TypeSafe key and the player's Wikipedia contact from .env.
"""

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

import wiki
from race import race

ROOT = Path(__file__).parent
PAGE = ROOT / "index.html"
DECIDE = ROOT / "decide.py"
PORT = 8000


def page_view(title: str) -> dict:
    page = wiki.page(title)
    return {"title": page["title"], "html": page["html"]}


def target_view(title: str) -> dict:
    canonical, _, summary = wiki.target_info(title)
    return {"title": canonical, "summary": summary}


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
            self.send_body(PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/status":
            self.send_json({"contact": bool(wiki.contact()), "jev": DECIDE.exists()})
        elif url.path == "/api/page":
            self.answer(lambda: page_view(query.get("title", "")))
        elif url.path == "/api/target":
            self.answer(lambda: target_view(query.get("title", "")))
        elif url.path == "/race":
            self.stream_race(query.get("start", ""), query.get("target", ""))
        else:
            self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/contact":
            return self.send_error(404)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def save():
            body = json.loads(raw or b"{}")
            wiki.set_contact(str(body.get("name", "")), str(body.get("email", "")))
            return {"ok": True}
        self.answer(save)

    def answer(self, produce):
        """Send produce()'s result as JSON, or the error a player can act on."""
        try:
            self.send_json(produce())
        except wiki.NoContact as error:
            self.send_json({"error": str(error), "needContact": True}, 403)
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
        except httpx.HTTPError:
            self.send_json({"error": "Could not reach Wikipedia. Check the connection and try again."}, 502)

    def stream_race(self, start: str, target: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            if not DECIDE.exists():
                raise ValueError("Jev is locked. Copy decide.py into the project folder to unlock it.")
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

    def send_json(self, value, status: int = 200):
        self.send_body(json.dumps(value).encode(), "application/json", status)

    def send_body(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"Open http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
