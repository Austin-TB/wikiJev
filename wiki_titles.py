"""Title helpers for English Wikipedia. A Python port of wikirun's server/titles.js."""

import re
from urllib.parse import unquote

# Namespace names and aliases from meta=siteinfo on en.wikipedia.org (checked 2026-09-16), lowercased.
# A link whose prefix before ":" is one of these is not an article.
NON_ARTICLE_NAMESPACES = {
    "media", "special", "talk", "user", "user talk", "wikipedia", "wikipedia talk", "project", "project talk",
    "wp", "wt", "file", "file talk", "image", "image talk", "mediawiki", "mediawiki talk", "template",
    "template talk", "tm", "help", "help talk", "category", "category talk", "portal", "portal talk", "draft",
    "draft talk", "mos", "mos talk", "timedtext", "timedtext talk", "module", "module talk", "event", "event talk",
}


def normalize_title(raw: str) -> str:
    """'volcanic_ash' -> 'Volcanic ash'. Mirrors how MediaWiki canonicalizes the text of a title."""
    title = re.sub(r"\s+", " ", raw.replace("_", " ")).strip()
    return title[:1].upper() + title[1:] if len(title[:1].upper()) == 1 else title


def is_article_title(title: str) -> bool:
    prefix, colon, _ = title.partition(":")
    return not (colon and prefix and prefix.strip().lower() in NON_ARTICLE_NAMESPACES)


def article_title(href: str | None) -> tuple[str, str] | None:
    """'/wiki/Volcanic_ash#Types' -> ('Volcanic ash', 'Types'); None for files, categories, edit and external links."""
    if not href or not href.startswith("/wiki/"):
        return None
    rest, _, fragment = href[len("/wiki/"):].partition("#")
    if not rest or "?" in rest:
        return None
    title = normalize_title(unquote(rest))
    if not title or not is_article_title(title):
        return None
    return title, unquote(fragment)
