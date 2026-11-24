"""Read Canvas assignments using the documented Canvas REST API."""

import json
import re
from collections.abc import Iterator
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RejectRedirects(HTTPRedirectHandler):
    """Keep credentials on the configured Canvas origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CanvasClient:
    def __init__(self, base_url: str, token: str):
        origin = urlsplit(base_url)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            raise ValueError("CANVAS_BASE_URL must be an HTTPS origin")
        if not token.strip():
            raise ValueError("CANVAS_API_TOKEN must be set")
        self.origin = origin
        self.token = token
        self.opener = build_opener(RejectRedirects())

    def assignments(self, course_id: int) -> Iterator[dict]:
        if course_id <= 0:
            raise ValueError("Canvas course ID must be positive")
        url = f"{self.origin.geturl().rstrip('/')}/api/v1/courses/{course_id}/assignments?per_page=100"
        seen = set()
        while url:
            page = urlsplit(url)
            if (
                (page.scheme, page.netloc) != (self.origin.scheme, self.origin.netloc)
                or not page.path.startswith("/api/v1/")
                or page.fragment
                or url in seen
            ):
                raise ValueError("Invalid Canvas pagination URL")
            seen.add(url)
            request = Request(url, headers={"Authorization": f"Bearer {self.token}"})
            with self.opener.open(request, timeout=15) as response:
                assignments = json.load(response)
                links = ", ".join(response.headers.get_all("Link", []))
            if not isinstance(assignments, list) or not all(isinstance(item, dict) for item in assignments):
                raise ValueError("Canvas returned an unexpected assignments response")
            yield from assignments
            next_link = re.search(r'<([^>]+)>\s*;\s*rel="next"', links)
            url = urljoin(url, next_link[1]) if next_link else ""
