"""Turns MediaWiki parse HTML into what players see. A Python port of wikirun's server/article.js.

Article content only: appendix sections, navboxes, references and hidden elements are removed,
and article links become game links (data-title, no href). The same link list goes to the
human player and to Jev, so both play by the same rules.
"""

import html as html_lib
import re
from urllib.parse import urlparse

import nh3
from bs4 import BeautifulSoup

from wiki_titles import article_title

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

REMOVE = ", ".join([
    "style", "link", "meta", "script", "noscript", "template", "audio", "video", "iframe", "object", "embed",
    "map", "form", "input", "button", "textarea", "select",
    ".mw-editsection", "sup.reference", ".mw-cite-backlink", ".reflist", ".references", ".mw-references-wrap",
    ".navbox", ".navbox-styles", ".authority-control", ".portal-bar", ".sistersitebox", ".side-box", ".metadata",
    ".ambox", ".ombox", ".tmbox", ".cmbox", ".fmbox", ".mbox-small", ".noprint", ".shortdescription",
    ".mw-empty-elt", "#toc", ".toc", ".mw-toc", ".catlinks", ".printfooter", ".Z3988", ".mw-jump-link",
])

IMAGE_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org", "wikimedia.org"}

TAGS = {
    "p", "a", "b", "i", "strong", "em", "u", "s", "small", "big", "sub", "sup", "span", "div", "br", "hr",
    "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "blockquote", "q", "cite", "code", "pre",
    "kbd", "samp", "var", "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td", "col", "colgroup",
    "figure", "figcaption", "img", "abbr", "bdi", "bdo", "time", "mark", "wbr", "ruby", "rt", "rp",
}
ATTRIBUTES = {
    "*": {"class", "id", "lang", "dir"},
    "a": {"data-title", "data-fragment"},
    "img": {"src", "srcset", "alt", "width", "height", "loading", "decoding"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start", "type", "reversed"},
    "li": {"value"},
    "abbr": {"title"},
    "time": {"datetime"},
}
DROP_WITH_CONTENT = {"style", "script", "textarea", "option", "noscript", "math", "svg"}


def _image_url(raw: str | None) -> str | None:
    if not raw:
        return None
    url = raw.strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.hostname in IMAGE_HOSTS else None


def _heading_text(node) -> str | None:
    if node.name == "h2":
        return node.get_text()
    if node.name == "div" and "mw-heading2" in (node.get("class") or []):
        h2 = node.find("h2")
        return h2.get_text() if h2 else ""
    return None


def _cut_appendix(root) -> None:
    nodes = [n for n in root.children if n.name]
    headings = []
    for index, node in enumerate(nodes):
        text = _heading_text(node)
        if text is not None:
            headings.append((index, " ".join(text.split()).lower() in APPENDIX_HEADINGS))
    cut_at = None
    for index, is_appendix in reversed(headings):
        if not is_appendix:
            break
        cut_at = index
    if cut_at is not None:
        for node in nodes[cut_at:]:
            node.decompose()


def transform_article(parser_html: str) -> tuple[str, list[str]]:
    """Return (sanitized html, titles players can click on this page)."""
    soup = BeautifulSoup(parser_html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup

    _cut_appendix(root)
    for node in root.select(REMOVE):
        node.decompose()
    for node in root.select("[style]"):
        if not node.decomposed and re.search(r"display\s*:\s*none", node.get("style", ""), re.I):
            node.decompose()

    for a in root.find_all("a"):
        target = article_title(a.get("href"))
        if not target or {"new", "mw-selflink"} & set(a.get("class") or []):
            a.unwrap()
            continue
        title, fragment = target
        a.attrs = {"data-title": title, **({"data-fragment": fragment} if fragment else {})}

    for img in root.find_all("img"):
        src = _image_url(img.get("src"))
        if not src:
            img.decompose()
            continue
        img["src"] = src
        img["loading"] = "lazy"
        srcset = []
        for part in (img.get("srcset") or "").split(","):
            if not part.strip():
                continue
            url, *descriptor = part.split()
            if url := _image_url(url):
                srcset.append(" ".join([url, *descriptor]))
        if srcset:
            img["srcset"] = ", ".join(srcset)
        elif img.has_attr("srcset"):
            del img["srcset"]

    # Wide tables scroll sideways on phones instead of stretching the page.
    for table in root.find_all("table"):
        if table.find_parent("table"):
            continue
        kind = "wiki-table-scroll wiki-infobox-wrap" if "infobox" in (table.get("class") or []) else "wiki-table-scroll"
        table.wrap(soup.new_tag("div", attrs={"class": kind}))

    inner = root.decode_contents() if root is not soup else str(soup)
    clean = nh3.clean(
        inner,
        tags=TAGS,
        clean_content_tags=DROP_WITH_CONTENT,
        attributes=ATTRIBUTES,
        url_schemes={"https"},
        link_rel=None,
        # Prefix ids so article anchors can never clash with the page's own element ids.
        id_prefix="wr-",
    )
    links = [html_lib.unescape(t) for t in re.findall(r'<a [^>]*data-title="([^"]*)"', clean)]
    return clean, list(dict.fromkeys(links))
