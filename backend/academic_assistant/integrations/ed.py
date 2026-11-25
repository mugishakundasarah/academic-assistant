"""Read Ed Discussion courses and threads through Ed's undocumented token API.

Ed publishes no API documentation. The endpoints and field shapes here follow
the community-maintained reverse-engineered notes in
https://github.com/smartspot2/edapi (``docs/api_docs.md``) and may change
without notice:

* ``GET /api/user``: ``{"user": {...}, "courses": [{"course": {"id", "code",
  "name", "status", ...}, "role": {...}}]}``
* ``GET /api/courses/{id}/threads?limit=&offset=&sort=new``:
  ``{"threads": [{"id", "number", "type", "title", "category", "created_at",
  "updated_at", "is_pinned", "is_answered", ...}]}``. The docs describe list
  entries as Thread objects, which also carry ``document``/``content``, but do
  not confirm the body is always present in the list, so callers that need
  text treat it as optional (``with_body=True``).
* ``GET /api/threads/{id}?view=1``: ``{"thread": {..., "course_id",
  "document", "content", "accepted_id", "answers": [{"id", "user_id",
  "document", "content", "is_endorsed", "is_anonymous", "created_at"}]},
  "users": [{"id", "role", "course_role", ...}]}``

Responses are parsed defensively: a response whose envelope has the wrong
shape raises ``ValueError``; a record without a usable ID is skipped; an
optional field with an unexpected type becomes ``None`` (or ``False`` for
flags). Names, emails and avatars in ``users`` are never returned.
"""

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .canvas import RejectRedirects

REGIONS = ("us", "eu", "au")
MAX_THREADS = 100
PAGE_SIZE = 50
MAX_ANSWERS = 20
TIMEOUT_SECONDS = 15
# Ed's firewall rejects urllib's default "Python-urllib" User-Agent with 403.
USER_AGENT = "academic-assistant/0.1"

# Elements of Ed's XML document format that end a line of text.
_BLOCK_TAGS = frozenset({
    "paragraph", "heading", "list-item", "callout", "pre", "snippet", "math", "figure",
    "document", "list", "break", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "div",
})


WEB_ORIGIN = "https://edstem.org"


def course_url(region: str, course_id: int, origin: str = WEB_ORIGIN) -> str:
    """The Ed web page for a course's discussion board."""
    return f"{origin}/{region}/courses/{course_id}/discussion"


def thread_url(region: str, course_id: int, thread_id: int, origin: str = WEB_ORIGIN) -> str:
    """The Ed web page for a thread."""
    return f"{course_url(region, course_id, origin)}/{thread_id}"


class _TextExtractor(HTMLParser):
    """Collect character data from Ed's XML ``content``; block elements end lines.

    ``HTMLParser`` never resolves external entities or DTDs, so untrusted
    markup cannot expand.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


_DOCTYPE = re.compile(r"<!DOCTYPE[^\[>]*(\[.*?\])?\s*>", re.IGNORECASE | re.DOTALL)


def xml_to_text(content: str) -> str:
    parser = _TextExtractor()
    parser.feed(_DOCTYPE.sub("", content))
    parser.close()
    return _tidy("".join(parser.parts))


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if line.strip() or (out and out[-1]):
            out.append(line if line.strip() else "")
    return "\n".join(out).strip()


def body_text(record: dict) -> str:
    """Plain text of a thread or comment: ``document`` if present, else ``content`` stripped of XML."""
    document = record.get("document")
    if isinstance(document, str) and document.strip():
        return _tidy(document)
    content = record.get("content")
    if isinstance(content, str) and content.strip():
        return xml_to_text(content)
    return ""


def _id(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _flag(value: object) -> bool:
    return value is True


def _time(value: object) -> str | None:
    """Normalize an ISO 8601 timestamp to UTC ``...Z``; ``None`` if it does not parse."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_id(value: object, what: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"Ed {what} ID must be positive")


def _records(data: dict, key: str, what: str) -> list[dict]:
    records = data.get(key)
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError(f"Ed returned an unexpected {what} response")
    return records


class EdClient:
    # Origin of the Ed web pages that links point to (the demo client overrides it).
    web_origin = WEB_ORIGIN

    def __init__(self, token: str, region: str = "us"):
        region = (region or "us").strip().lower()
        if region not in REGIONS:
            raise ValueError("ED_REGION must be one of us, eu or au")
        token = (token or "").strip()
        # A token with whitespace or control characters would be rejected by
        # http.client with an error that echoes the header value.
        if not token or any(ch.isspace() or not ch.isprintable() for ch in token):
            raise ValueError("ED_API_TOKEN must be set")
        self.region = region
        self.origin = f"https://{region}.edstem.org"
        self.token = token
        self.opener = build_opener(RejectRedirects())

    def courses(self) -> list[dict]:
        """Return ``{id, code, name}`` for each course whose Ed status is ``active``."""
        result = []
        for entry in _records(self._get("/api/user", "user"), "courses", "user"):
            course = entry.get("course")
            if not isinstance(course, dict) or course.get("status") != "active":
                continue
            course_id = _id(course.get("id"))
            if course_id is None:
                continue
            result.append({
                "id": course_id,
                "code": _str(course.get("code")),
                "name": _str(course.get("name")) or f"Course {course_id}",
            })
        return result

    def course_url(self, course_id: int) -> str:
        return course_url(self.region, course_id, self.web_origin)

    def threads(self, course_id: int, limit: int = 20, with_body: bool = False) -> list[dict]:
        """Return up to ``limit`` (at most ``MAX_THREADS``) recent threads, newest first.

        With ``with_body`` each summary also has ``updated_at`` and ``text``:
        the plain text when the list entry carries ``document`` or
        ``content``, else ``None`` (fetch it with ``thread()``).
        """
        _check_id(course_id, "course")
        if type(limit) is not int or limit <= 0:
            raise ValueError("Ed thread limit must be positive")
        limit = min(limit, MAX_THREADS)
        result: list[dict] = []
        seen: set[int] = set()
        offset = 0
        while len(result) < limit:
            size = min(PAGE_SIZE, limit - offset)
            if size <= 0:
                break
            query = urlencode({"limit": size, "offset": offset, "sort": "new"})
            page = _records(self._get(f"/api/courses/{course_id}/threads?{query}", "threads"), "threads", "threads")
            for record in page:
                summary = self._summary(record, course_id, with_body)
                # Offset pages can overlap when new threads arrive between requests.
                if summary is not None and summary["id"] not in seen:
                    seen.add(summary["id"])
                    result.append(summary)
            if len(page) < size:
                break
            offset += size
        return result[:limit]

    def thread(self, thread_id: int) -> dict:
        """Return one thread's plain text and up to ``MAX_ANSWERS`` answers."""
        _check_id(thread_id, "thread")
        data = self._get(f"/api/threads/{thread_id}?view=1", "thread")
        thread = data.get("thread")
        if not isinstance(thread, dict) or _id(thread.get("id")) is None:
            raise ValueError("Ed returned an unexpected thread response")
        users = data.get("users")
        roles = {}
        if isinstance(users, list):
            for user in users:
                if isinstance(user, dict) and _id(user.get("id")) is not None:
                    roles[user["id"]] = _str(user.get("course_role")) or _str(user.get("role"))
        answers = thread.get("answers")
        if answers is None:
            answers = []
        if not isinstance(answers, list):
            raise ValueError("Ed returned an unexpected thread response")
        accepted_id = _id(thread.get("accepted_id"))
        course_id = _id(thread.get("course_id"))
        result_answers = []
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            if len(result_answers) == MAX_ANSWERS:
                break
            anonymous = _flag(answer.get("is_anonymous"))
            answer_id = _id(answer.get("id"))
            result_answers.append({
                # Anonymous answers keep their author's role hidden too.
                "author_role": None if anonymous else roles.get(_id(answer.get("user_id"))),
                "text": body_text(answer),
                "endorsed": _flag(answer.get("is_endorsed")),
                "accepted": answer_id is not None and answer_id == accepted_id,
                "created_at": _time(answer.get("created_at")),
            })
        return {
            "id": thread["id"],
            "course_id": course_id,
            "title": _str(thread.get("title")) or "Untitled thread",
            "type": _str(thread.get("type")),
            "category": _str(thread.get("category")),
            "created_at": _time(thread.get("created_at")),
            "text": body_text(thread),
            "url": thread_url(self.region, course_id, thread["id"], self.web_origin) if course_id else None,
            "answers": result_answers,
        }

    def _summary(self, record: dict, course_id: int, with_body: bool = False) -> dict | None:
        thread_id = _id(record.get("id"))
        if thread_id is None:
            return None
        number = record.get("number")
        summary = {
            "id": thread_id,
            "number": number if type(number) is int else None,
            "title": _str(record.get("title")) or "Untitled thread",
            "type": _str(record.get("type")),
            "category": _str(record.get("category")),
            "created_at": _time(record.get("created_at")),
            "is_pinned": _flag(record.get("is_pinned")),
            "is_answered": _flag(record.get("is_answered")),
            "url": thread_url(self.region, course_id, thread_id, self.web_origin),
        }
        if with_body:
            has_body = isinstance(record.get("document"), str) or isinstance(record.get("content"), str)
            summary["updated_at"] = _time(record.get("updated_at"))
            summary["text"] = body_text(record) if has_body else None
        return summary

    def _get(self, path: str, what: str) -> dict:
        # Paths are built here from validated integers, never from response
        # data, so the token only ever goes to the fixed regional origin.
        request = Request(
            f"{self.origin}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError(f"Ed returned an unexpected {what} response")
        return data
