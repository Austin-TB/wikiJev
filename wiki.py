"""Wikipedia pages via the public MediaWiki API. Plain code, no AI.

`page()` returns what a player sees and `links()` what Jev chooses from. Both come
from the same transform, so humans and Jev play by the same rules.
"""

import hashlib
import json
import os
import re
import time
from collections import deque
from pathlib import Path

import httpx
from dotenv import load_dotenv, set_key

from article import transform_article
from wiki_titles import is_article_title, normalize_title

ENV_FILE = Path(__file__).parent / ".env"
load_dotenv(ENV_FILE)

API = "https://en.wikipedia.org/w/api.php"
PER_MINUTE = 150  # Wikimedia allows 200 a minute to clients with contact details; stay well under
_started: deque[float] = deque()
_http = httpx.Client(timeout=20)

# One file per page. Races become repeatable, a room can share a pre-warmed cache
# (see warm.py), and timings measure the model rather than the network.
CACHE_DIR = Path(__file__).parent / "wiki_cache"


class NoContact(Exception):
    """Raised until the player has given a name and email for the User-Agent."""


def contact() -> str:
    return os.environ.get("WIKIPEDIA_CONTACT", "").strip()


def set_contact(name: str, email: str) -> None:
    """Save the player's contact details to .env. Wikipedia's API policy asks for them."""
    name, email = " ".join(name.split()), email.strip()
    if not name or not re.fullmatch(r"[^@\s;]+@[^@\s;]+\.[^@\s;]+", email):
        raise ValueError("Enter your name and a valid email address.")
    value = f"{name}; {email}"
    set_key(ENV_FILE, "WIKIPEDIA_CONTACT", value)
    os.environ["WIKIPEDIA_CONTACT"] = value


def _api(**params) -> dict:
    """One API call, under the rate limit, retrying 429/503 as Retry-After asks."""
    # Wikimedia allows 10 requests a minute without contact details in the User-Agent, 200 with them.
    if not re.search(r"@|https?://", contact()):
        raise NoContact("Add your name and email first. Wikipedia's API policy requires them.")
    params |= {"format": "json", "formatversion": 2}
    headers = {"User-Agent": f"aic-handson-wikirace/0.1 ({contact()})"}
    for attempt in range(3):
        while _started and time.monotonic() - _started[0] >= 60:
            _started.popleft()
        if len(_started) >= PER_MINUTE:
            time.sleep(60 - (time.monotonic() - _started[0]))
        _started.append(time.monotonic())
        response = _http.get(API, params=params, headers=headers)
        if response.status_code in (429, 503) and attempt < 2:
            time.sleep(min(float(response.headers.get("Retry-After") or 5), 60))
            continue
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(data["error"].get("info", data["error"]["code"]))
        return data


def _cached(key: str, fetch):
    path = CACHE_DIR / f"{hashlib.sha1(key.encode()).hexdigest()}.json"
    if path.exists():
        return json.loads(path.read_text())
    value = fetch()
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(value))
    return value


def page(title: str) -> dict:
    """{"title": canonical title, "html": what the player sees, "links": titles they can click}."""
    title = normalize_title(title)
    if not title:
        raise ValueError("Enter a page title.")

    def fetch():
        data = _api(action="parse", page=title, prop="text", redirects=1,
                    disableeditsection=1, disabletoc=1, disablelimitreport=1)["parse"]
        if not is_article_title(data["title"]):
            raise ValueError(f"{data['title']} is not an article.")
        html, links = transform_article(data["text"])
        return {"title": data["title"], "html": html, "links": links}

    try:
        return _cached(f"page:{title}", fetch)
    except ValueError as error:
        if "doesn't exist" in str(error):
            raise ValueError(f"No Wikipedia article named {title!r}.") from None
        raise


def links(title: str) -> tuple[str, list[str]]:
    """Resolve `title` (following redirects) and return (canonical title, links a player can click)."""
    p = page(title)
    return p["title"], p["links"]


def target_info(title: str) -> tuple[str, set[str], str]:
    """Return the target's canonical title, every title that redirects to it, and a short summary."""
    title = normalize_title(title)
    if not title:
        raise ValueError("Enter a target.")

    def fetch():
        names, summary, cont = set(), "", {}
        while True:
            data = _api(action="query", titles=title, redirects=1, prop="redirects|extracts", rdlimit="max",
                        rdnamespace=0, exintro=1, explaintext=1, exsentences=2, **cont)
            found = data["query"]["pages"][0]
            if found.get("missing") or found.get("invalid"):
                raise ValueError(f"No Wikipedia article named {title!r}.")
            names |= {r["title"] for r in found.get("redirects", [])}
            summary = found.get("extract") or summary
            if "continue" not in data:
                return found["title"], sorted(names | {found["title"]}), summary
            cont = data["continue"]

    canonical, names, summary = _cached(f"target:{title}", fetch)
    return canonical, set(names), summary
