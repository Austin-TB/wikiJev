"""Wikipedia pages via the public MediaWiki API. Plain code, no AI.

`links()` returns the links Jev can click on a page: the article links in its body. These are
the rules wikirun uses for its human players (a port of its server/article.js), so Jev here
can click exactly the links a player in the room can.
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

API = "https://en.wikipedia.org/w/api.php"
PLACEHOLDER = "Your Name; you@example.com"  # WIKIPEDIA_CONTACT in .env.example
_http = httpx.Client(timeout=20)

# One file per page. Races see the same pages every time, the repo can ship the pages people
# try first, and timings measure the model rather than the network.
CACHE_DIR = Path(__file__).parent / "wiki_cache"

# Namespace names and aliases from meta=siteinfo on en.wikipedia.org (checked 2026-09-16), lowercased.
# A link whose prefix before ":" is one of these is not an article.
NON_ARTICLE_NAMESPACES = {
    "media", "special", "talk", "user", "user talk", "wikipedia", "wikipedia talk", "project", "project talk",
    "wp", "wt", "file", "file talk", "image", "image talk", "mediawiki", "mediawiki talk", "template",
    "template talk", "tm", "help", "help talk", "category", "category talk", "portal", "portal talk", "draft",
    "draft talk", "mos", "mos talk", "timedtext", "timedtext talk", "module", "module talk", "event", "event talk",
}

# Level-2 headings that start the end-of-article material. The cut happens at the first of these
# that is followed only by other such headings, so a content section named "Sources" survives.
APPENDIX_HEADINGS = {
    "see also", "notes", "note", "footnotes", "endnotes", "references", "reference", "citations", "sources",
    "source", "notes and references", "references and notes", "notes and sources", "sources and notes",
    "notes and citations", "citations and notes", "explanatory notes", "informational notes", "citation notes",
    "general references", "general and cited references", "specific references", "cited sources", "sources cited",
    "general sources", "works cited", "cited works", "bibliography", "further reading", "external links",
    "external link", "references and further reading", "further reading and external links", "literature",
}

# Everything a player doesn't see: navboxes, references, hidden and non-article elements. The
# last line is what wikirun's sanitiser drops with its content, so their links go too.
REMOVE = ", ".join([
    "style", "link", "meta", "script", "noscript", "template", "audio", "video", "iframe", "object", "embed",
    "map", "form", "input", "button", "textarea", "select",
    ".mw-editsection", "sup.reference", ".mw-cite-backlink", ".reflist", ".references", ".mw-references-wrap",
    ".navbox", ".navbox-styles", ".authority-control", ".portal-bar", ".sistersitebox", ".side-box", ".metadata",
    ".ambox", ".ombox", ".tmbox", ".cmbox", ".fmbox", ".mbox-small", ".noprint", ".shortdescription",
    ".mw-empty-elt", "#toc", ".toc", ".mw-toc", ".catlinks", ".printfooter", ".Z3988", ".mw-jump-link",
    "math", "svg", "option",
])


class NoContact(Exception):
    """Raised when .env has no WIKIPEDIA_CONTACT with an email address or URL, or still has the placeholder."""


def normalize_title(raw: str) -> str:
    """'volcanic_ash' -> 'Volcanic ash'. Mirrors how MediaWiki canonicalizes the text of a title."""
    title = re.sub(r"\s+", " ", raw.replace("_", " ")).strip()
    return title[:1].upper() + title[1:] if len(title[:1].upper()) == 1 else title


def is_article_title(title: str) -> bool:
    prefix, colon, _ = title.partition(":")
    return not (colon and prefix and prefix.strip().lower() in NON_ARTICLE_NAMESPACES)


def article_title(href: str | None) -> str | None:
    """'/wiki/Volcanic_ash#Types' -> 'Volcanic ash'; None for files, categories, edit and external links."""
    if not href or not href.startswith("/wiki/"):
        return None
    rest = href[len("/wiki/"):].partition("#")[0]
    if not rest or "?" in rest:
        return None
    title = normalize_title(unquote(rest))
    return title if title and is_article_title(title) else None


def _cut_appendix(root) -> None:
    nodes = [n for n in root.children if n.name]
    headings = []
    for index, node in enumerate(nodes):
        if node.name == "h2":
            text = node.get_text()
        elif node.name == "div" and "mw-heading2" in (node.get("class") or []):
            h2 = node.find("h2")
            text = h2.get_text() if h2 else ""
        else:
            continue
        headings.append((index, " ".join(text.split()).lower() in APPENDIX_HEADINGS))
    cut_at = None
    for index, is_appendix in reversed(headings):
        if not is_appendix:
            break
        cut_at = index
    if cut_at is not None:
        for node in nodes[cut_at:]:
            node.decompose()


def body_links(parser_html: str) -> list[str]:
    """Titles of the article links a player can click in MediaWiki parse HTML, in first-seen order."""
    soup = BeautifulSoup(parser_html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup

    _cut_appendix(root)
    for node in root.select(REMOVE):
        node.decompose()
    for node in root.select("[style]"):
        if not node.decomposed and re.search(r"display\s*:\s*none", node.get("style", ""), re.I):
            node.decompose()

    # Red links (class "new") lead to missing pages, and a self-link leads nowhere.
    titles = [article_title(a.get("href")) for a in root.find_all("a")
              if not {"new", "mw-selflink"} & set(a.get("class") or [])]
    return list(dict.fromkeys(title for title in titles if title))


def _api(**params) -> dict:
    """One API call, retrying 429/503 as Retry-After asks."""
    # Wikimedia allows 10 requests a minute without contact details in the User-Agent, 200 with them.
    contact = os.environ.get("WIKIPEDIA_CONTACT", "").strip()
    if contact == PLACEHOLDER or not re.search(r"@|https?://", contact):
        raise NoContact("Wikipedia's API policy asks for your contact details. Put your name and email "
                        f'in .env on this line, then start the app again:\nWIKIPEDIA_CONTACT="{PLACEHOLDER}"')
    params |= {"format": "json", "formatversion": 2}
    headers = {"User-Agent": f"aic-handson-wikirace/0.1 ({contact})"}
    for attempt in range(3):
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


def links(title: str) -> tuple[str, list[str]]:
    """Resolve `title` (following redirects) and return (canonical title, links a player can click)."""
    title = normalize_title(title)
    if not title:
        raise ValueError("Enter a page title.")

    def fetch():
        data = _api(action="parse", page=title, prop="text", redirects=1,
                    disableeditsection=1, disabletoc=1, disablelimitreport=1)["parse"]
        if not is_article_title(data["title"]):
            raise ValueError(f"{data['title']} is not an article.")
        return {"title": data["title"], "links": body_links(data["text"])}

    try:
        page = _cached(f"page:{title}", fetch)
    except ValueError as error:
        if "doesn't exist" in str(error):
            raise ValueError(f"No Wikipedia article named {title!r}.") from None
        raise
    return page["title"], page["links"]


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
