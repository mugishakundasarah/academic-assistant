"""Local stdio MCP server for read-only Canvas assignment access."""

import os
from http.client import HTTPException
from typing import Annotated
from urllib.error import HTTPError

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from typing_extensions import TypedDict

from .canvas import CanvasClient


class CanvasAssignment(TypedDict):
    id: int
    name: str
    due_at: str | None
    html_url: str | None


mcp = FastMCP("Academic Assistant Canvas")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def list_canvas_assignments(
    course_id: Annotated[int, Field(strict=True, gt=0)],
) -> list[CanvasAssignment]:
    """List assignment IDs, names, due dates, and links for a Canvas course."""
    try:
        client = CanvasClient(os.getenv("CANVAS_BASE_URL", ""), os.getenv("CANVAS_API_TOKEN", ""))
    except ValueError:
        raise ToolError("Configure CANVAS_BASE_URL as an HTTPS origin and set CANVAS_API_TOKEN.") from None

    result: list[CanvasAssignment] = []
    try:
        for assignment in client.assignments(course_id):
            assignment_id = assignment.get("id")
            name = assignment.get("name")
            due_at = assignment.get("due_at")
            html_url = assignment.get("html_url")
            if (
                type(assignment_id) is not int
                or not isinstance(name, str)
                or (due_at is not None and not isinstance(due_at, str))
                or (html_url is not None and not isinstance(html_url, str))
            ):
                raise ValueError("Unexpected assignment fields")
            result.append(CanvasAssignment(id=assignment_id, name=name, due_at=due_at, html_url=html_url))
    except HTTPError as error:
        raise ToolError(f"Canvas request failed (HTTP {error.code}).") from None
    except (ValueError, HTTPException):
        raise ToolError("Canvas returned an invalid assignments response.") from None
    except OSError:
        raise ToolError("Could not reach Canvas.") from None

    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
