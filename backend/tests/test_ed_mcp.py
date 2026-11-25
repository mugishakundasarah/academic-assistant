import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOOLS = ["get_ed_thread", "list_ed_courses", "list_ed_threads"]

FIXTURE_SERVER = """
from unittest.mock import patch
from urllib.error import HTTPError
from academic_assistant.integrations import ed_mcp

def thread(thread_id):
    if thread_id == 404:
        raise HTTPError("https://us.edstem.org/api/threads/404", 404, "secret detail", None, None)
    if thread_id == 500:
        raise ValueError("raw parser detail")
    return {
        "id": thread_id, "course_id": 101, "title": "Recursion question", "type": "question",
        "category": "Lectures", "created_at": "2026-11-21T09:00:00Z", "text": "How?",
        "url": "https://edstem.org/us/courses/101/discussion/%d" % thread_id,
        "answers": [{"author_role": "staff", "text": "Like this.", "endorsed": True, "accepted": True,
                     "created_at": "2026-11-21T10:00:00Z"}],
    }

with patch.object(ed_mcp, "EdClient") as client:
    client.return_value.courses.return_value = [{"id": 101, "code": "CS 61A", "name": "SICP"}]
    client.return_value.threads.side_effect = lambda course_id, limit: [{
        "id": 900, "number": 12, "title": "Recursion question limit=%d" % limit, "type": "question",
        "category": "Lectures", "created_at": "2026-11-21T09:00:00Z", "is_pinned": False,
        "is_answered": True, "url": "https://edstem.org/us/courses/%d/discussion/900" % course_id,
    }]
    client.return_value.thread.side_effect = thread
    ed_mcp.mcp.run(transport="stdio")
"""


def error_text(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


class EdMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_and_read_only_tools_over_stdio(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", FIXTURE_SERVER],
            env={"ED_API_TOKEN": "fixture-token", "ED_REGION": "us"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual(sorted(tool.name for tool in tools.tools), TOOLS)
                for tool in tools.tools:
                    self.assertTrue(tool.annotations.readOnlyHint, tool.name)
                    self.assertFalse(tool.annotations.destructiveHint, tool.name)

                for name, arguments in (
                    ("list_ed_threads", {"course_id": 0}),
                    ("list_ed_threads", {"course_id": "101"}),
                    ("list_ed_threads", {"course_id": 101, "limit": 0}),
                    ("list_ed_threads", {"course_id": 101, "limit": 51}),
                    ("get_ed_thread", {"thread_id": -1}),
                ):
                    with self.subTest(name=name, arguments=arguments):
                        self.assertTrue((await session.call_tool(name, arguments)).isError)

                courses = await session.call_tool("list_ed_courses", {})
                self.assertFalse(courses.isError, courses.content)
                self.assertEqual(courses.structuredContent, {"result": [{"id": 101, "code": "CS 61A", "name": "SICP"}]})

                threads = await session.call_tool("list_ed_threads", {"course_id": 101})
                self.assertFalse(threads.isError, threads.content)
                self.assertEqual(threads.structuredContent, {"result": [{
                    "id": 900, "number": 12, "title": "Recursion question limit=20", "type": "question",
                    "category": "Lectures", "created_at": "2026-11-21T09:00:00Z", "is_pinned": False,
                    "is_answered": True, "url": "https://edstem.org/us/courses/101/discussion/900",
                }]})
                limited = await session.call_tool("list_ed_threads", {"course_id": 101, "limit": 50})
                self.assertEqual(limited.structuredContent["result"][0]["title"], "Recursion question limit=50")

                thread = await session.call_tool("get_ed_thread", {"thread_id": 900})
                self.assertFalse(thread.isError, thread.content)
                self.assertEqual(thread.structuredContent, {
                    "id": 900, "title": "Recursion question", "type": "question", "category": "Lectures",
                    "created_at": "2026-11-21T09:00:00Z", "text": "How?",
                    "url": "https://edstem.org/us/courses/101/discussion/900",
                    "answers": [{"author_role": "staff", "text": "Like this.", "endorsed": True, "accepted": True,
                                 "created_at": "2026-11-21T10:00:00Z"}],
                })

                missing = await session.call_tool("get_ed_thread", {"thread_id": 404})
                self.assertTrue(missing.isError)
                self.assertIn("Ed request failed (HTTP 404).", error_text(missing))
                self.assertNotIn("secret detail", error_text(missing))
                broken = await session.call_tool("get_ed_thread", {"thread_id": 500})
                self.assertTrue(broken.isError)
                self.assertIn("Ed returned an unexpected response.", error_text(broken))
                self.assertNotIn("raw parser detail", error_text(broken))

    async def test_production_entry_point_discovers_tools_without_credentials(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "academic_assistant.integrations.ed_mcp"],
            env={"ED_API_TOKEN": "", "ED_REGION": ""},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual(sorted(tool.name for tool in tools.tools), TOOLS)
                for name, arguments in (("list_ed_courses", {}), ("list_ed_threads", {"course_id": 9}),
                                        ("get_ed_thread", {"thread_id": 9})):
                    with self.subTest(name=name):
                        result = await session.call_tool(name, arguments)
                        self.assertTrue(result.isError)
                        self.assertIn("Set ED_API_TOKEN", error_text(result))


if __name__ == "__main__":
    unittest.main()
