import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


FIXTURE_SERVER = """
from unittest.mock import patch
from academic_assistant.integrations import canvas_mcp

with patch.object(canvas_mcp, "CanvasClient") as client:
    client.return_value.assignments.return_value = iter([{
        "id": 11,
        "name": "Fixture assignment",
        "due_at": "2026-12-01T18:00:00Z",
        "html_url": "https://canvas.example.edu/courses/9/assignments/11",
        "description": "<p>Excluded from the tool response</p>",
    }])
    canvas_mcp.mcp.run(transport="stdio")
"""


class CanvasMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_discovery_and_assignment_pull_over_stdio(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", FIXTURE_SERVER],
            env={
                "CANVAS_BASE_URL": "https://canvas.example.edu",
                "CANVAS_API_TOKEN": "fixture-token",
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual([tool.name for tool in tools.tools], ["list_canvas_assignments"])
                self.assertTrue(tools.tools[0].annotations.readOnlyHint)
                bad = await session.call_tool("list_canvas_assignments", {"course_id": 0})
                self.assertTrue(bad.isError)
                result = await session.call_tool("list_canvas_assignments", {"course_id": 9})
                self.assertFalse(result.isError, result.content)
                self.assertEqual(
                    result.structuredContent,
                    {"result": [{
                        "id": 11,
                        "name": "Fixture assignment",
                        "due_at": "2026-12-01T18:00:00Z",
                        "html_url": "https://canvas.example.edu/courses/9/assignments/11",
                    }]},
                )

    async def test_production_entry_point_discovers_tool_without_credentials(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "academic_assistant.integrations.canvas_mcp"],
            env={"CANVAS_BASE_URL": "", "CANVAS_API_TOKEN": ""},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual([tool.name for tool in tools.tools], ["list_canvas_assignments"])
                result = await session.call_tool("list_canvas_assignments", {"course_id": 9})
                self.assertTrue(result.isError)
