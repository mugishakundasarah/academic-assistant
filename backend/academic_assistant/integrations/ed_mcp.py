"""Local stdio MCP server for read-only Ed Discussion access.

Ed's API is undocumented; see ``ed.py`` for the endpoints and fields used.
"""

import os
from http.client import HTTPException
from typing import Annotated
from urllib.error import HTTPError

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import TypedDict

from ..env import load_env_file
from .ed import EdClient


class EdCourse(TypedDict):
    id: int
    code: str | None
    name: str


class EdThreadSummary(TypedDict):
    id: int
    number: int | None
    title: str
    type: str | None
    category: str | None
    created_at: str | None
    is_pinned: bool
    is_answered: bool
    url: str


class EdAnswer(TypedDict):
    author_role: str | None
    text: str
    endorsed: bool
    accepted: bool
    created_at: str | None


class EdThread(TypedDict):
    id: int
    title: str
    type: str | None
    category: str | None
    created_at: str | None
    text: str
    url: str | None
    answers: list[EdAnswer]


mcp = FastMCP("Academic Assistant Ed Discussion")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


def _client() -> EdClient:
    try:
        return EdClient(os.getenv("ED_API_TOKEN", ""), os.getenv("ED_REGION", ""))
    except ValueError:
        raise ToolError("Set ED_API_TOKEN and set ED_REGION to us, eu or au.") from None


def _call(fetch):
    # Messages are fixed strings: exception text could carry request details.
    try:
        return fetch(_client())
    except HTTPError as error:
        raise ToolError(f"Ed request failed (HTTP {error.code}).") from None
    except (ValueError, TypeError, HTTPException):
        raise ToolError("Ed returned an unexpected response.") from None
    except OSError:
        raise ToolError("Could not reach Ed.") from None


@mcp.tool(annotations=READ_ONLY)
def list_ed_courses() -> list[EdCourse]:
    """List your active Ed Discussion courses with their IDs, codes, and names."""
    return [EdCourse(**course) for course in _call(lambda client: client.courses())]


@mcp.tool(annotations=READ_ONLY)
def list_ed_threads(
    course_id: Annotated[int, Field(strict=True, gt=0)],
    limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
) -> list[EdThreadSummary]:
    """List recent threads in an Ed Discussion course, newest first, with links."""
    return [EdThreadSummary(**thread) for thread in _call(lambda client: client.threads(course_id, limit))]


@mcp.tool(annotations=READ_ONLY)
def get_ed_thread(thread_id: Annotated[int, Field(strict=True, gt=0)]) -> EdThread:
    """Get one Ed Discussion thread's plain text and its answers (author names are not included)."""
    thread = _call(lambda client: client.thread(thread_id))
    thread.pop("course_id", None)
    return EdThread(**thread)


if __name__ == "__main__":
    load_env_file()
    mcp.run(transport="stdio")
