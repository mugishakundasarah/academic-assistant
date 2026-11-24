"""Convert Canvas HTML bodies to plain text and safe links using only the standard library."""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

# Elements whose start and end separate paragraphs.
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "dd", "details", "div", "dl", "dt", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav",
    "ol", "p", "pre", "section", "summary", "table", "ul",
})
# Elements that end a line without starting a new paragraph.
_LINE_TAGS = frozenset({"br", "tr", "li"})
# Elements whose text is never shown to the reader.
_HIDDEN_TAGS = frozenset({"head", "iframe", "noscript", "object", "script", "style", "template", "title", "svg"})
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})

_PARAGRAPH = "\x00P"
_LINE = "\x00L"
_PRE = "\x00R"
# Any control character makes a URL suspect (browsers silently drop some of
# them, which hides schemes such as "java\tscript:"), so such URLs are rejected.
_URL_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_url(href: object, base_url: str) -> str | None:
    """Return ``href`` as an absolute http(s) URL resolved against ``base_url``, or None.

    Fragment-only, javascript:, data:, mailto: and any other non-http(s) scheme
    are rejected, as are URLs that embed credentials or contain any control
    character (U+0000-U+001F, U+007F). Surrounding spaces are ignored.
    """
    if not isinstance(href, str) or _URL_CONTROL.search(href):
        return None
    href = href.strip(" ")
    if not href or href.startswith("#"):
        return None
    try:
        absolute = urljoin(base_url.rstrip("/") + "/", href)
        parts = urlsplit(absolute)
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return absolute


def link_kind(url: str) -> str:
    """Canvas file links (and attachments) are "file"; everything else is "link"."""
    return "file" if "/files/" in urlsplit(url).path else "link"


class _CanvasHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[dict] = []
        self.hidden_depth = 0
        self.pre_depth = 0
        self.anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _HIDDEN_TAGS:
            if tag not in _VOID_TAGS:
                self.hidden_depth += 1
            return
        if self.hidden_depth:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append(_PARAGRAPH)
            if tag == "pre":
                if not self.pre_depth:
                    self.parts.append(_PRE)
                self.pre_depth += 1
        elif tag in _LINE_TAGS:
            self.parts.append(_LINE)
            if tag == "li":
                self.parts.append("- ")
        elif tag in ("td", "th"):
            self.parts.append(" ")
        elif tag == "a":
            self._finish_anchor()
            url = safe_url(dict(attrs).get("href"), self.base_url)
            if url:
                self.anchor = {"url": url, "text": []}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _HIDDEN_TAGS:
            if tag not in _VOID_TAGS and self.hidden_depth:
                self.hidden_depth -= 1
            return
        if self.hidden_depth:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append(_PARAGRAPH)
            if tag == "pre" and self.pre_depth:
                self.pre_depth -= 1
        elif tag in ("li", "tr"):
            self.parts.append(_LINE)
        elif tag == "a":
            self._finish_anchor()

    def handle_data(self, data):
        if self.hidden_depth:
            return
        if not self.pre_depth:
            data = re.sub(r"\s+", " ", data)
            if data.startswith(" ") and self.parts and self.parts[-1].endswith(" "):
                data = data[1:]
        if not data:
            return
        self.parts.append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def _finish_anchor(self):
        if self.anchor is None:
            return
        title = re.sub(r"\s+", " ", "".join(self.anchor["text"])).strip()
        self.links.append({"title": title, "url": self.anchor["url"]})
        self.anchor = None

    def close(self):
        super().close()
        self._finish_anchor()

    def text(self) -> str:
        raw = "".join(self.parts)
        paragraphs = []
        for block in raw.split(_PARAGRAPH):
            if block.startswith(_PRE):
                # Preformatted text keeps each line's indentation. Blank lines
                # are dropped so they cannot read as paragraph breaks.
                lines = block[len(_PRE):].replace("\r\n", "\n").replace(_LINE, "\n").split("\n")
                lines = [line.rstrip() for line in lines if line.strip()]
            else:
                lines = [line.strip() for line in block.split(_LINE)]
                lines = [line for line in lines if line and line != "-"]
            if lines:
                paragraphs.append("\n".join(lines))
        return "\n\n".join(paragraphs)


def _default_title(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1] if path else ""
    return name or urlsplit(url).hostname or url


def html_to_text_and_links(html: object, base_url: str) -> tuple[str, list[dict]]:
    """Return plain text (paragraphs joined by a blank line) and safe links from Canvas HTML.

    Links are ``{"title", "url", "kind"}`` dicts with absolute http(s) URLs,
    deduplicated by URL in document order.
    """
    if not isinstance(html, str) or not html.strip():
        return "", []
    parser = _CanvasHTMLParser(base_url)
    parser.feed(html)
    parser.close()
    return parser.text(), dedupe_links(
        {"title": link["title"] or _default_title(link["url"]), "url": link["url"], "kind": link_kind(link["url"])}
        for link in parser.links
    )


def dedupe_links(links) -> list[dict]:
    seen = set()
    result = []
    for link in links:
        if link["url"] in seen:
            continue
        seen.add(link["url"])
        result.append(link)
    return result
