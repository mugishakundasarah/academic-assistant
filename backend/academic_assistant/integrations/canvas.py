"""Read Canvas courses, assignments, and announcements using the documented Canvas REST API."""

import json
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RejectRedirects(HTTPRedirectHandler):
    """Keep credentials on the configured Canvas origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _canvas_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    @property
    def base_url(self) -> str:
        """The Canvas origin without a trailing slash, used to resolve relative links."""
        return f"{self.origin.scheme}://{self.origin.netloc}"

    def courses(self) -> Iterator[dict]:
        """Yield the courses with an active enrollment for the token's user."""
        return self._paginate("/api/v1/courses?enrollment_state=active&per_page=100", "courses")

    def assignments(self, course_id: int, include_submission: bool = False) -> Iterator[dict]:
        """Yield a course's assignments, optionally with the user's submission embedded."""
        self._check_course_id(course_id)
        path = f"/api/v1/courses/{course_id}/assignments?per_page=100"
        if include_submission:
            path += "&include[]=submission"
        return self._paginate(path, "assignments")

    def announcements(self, course_id: int, start_date: datetime, end_date: datetime) -> Iterator[dict]:
        """Yield a course's announcements posted between ``start_date`` and ``end_date``."""
        self._check_course_id(course_id)
        path = (
            f"/api/v1/announcements?context_codes[]=course_{course_id}"
            f"&start_date={_canvas_time(start_date)}&end_date={_canvas_time(end_date)}&per_page=100"
        )
        return self._paginate(path, "announcements")

    @staticmethod
    def _check_course_id(course_id: int) -> None:
        if type(course_id) is not int or course_id <= 0:
            raise ValueError("Canvas course ID must be positive")

    def _paginate(self, path: str, what: str) -> Iterator[dict]:
        # Validate eagerly so argument errors surface at call time; fetch lazily.
        url = f"{self.base_url}{path}"
        return self._pages(url, what)

    def _pages(self, url: str, what: str) -> Iterator[dict]:
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
                records = json.load(response)
                links = ", ".join(response.headers.get_all("Link", []))
            if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
                raise ValueError(f"Canvas returned an unexpected {what} response")
            yield from records
            next_link = re.search(r'<([^>]+)>\s*;\s*rel="next"', links)
            url = urljoin(url, next_link[1]) if next_link else ""
