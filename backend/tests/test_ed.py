import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from academic_assistant.integrations import __main__ as cli
from academic_assistant.integrations.ed import EdClient, body_text, xml_to_text

TOKEN = "ed-fixture-token"


def response(body):
    stream = io.BytesIO((body if isinstance(body, str) else json.dumps(body)).encode())
    stream.headers = Message()
    return stream


def thread_record(thread_id, **extra):
    return {
        "id": thread_id, "number": thread_id % 1000, "type": "question", "title": f"Thread {thread_id}",
        "category": "Homework", "subcategory": "HW1", "created_at": "2026-11-20T10:00:00.123456+11:00",
        "updated_at": "2026-11-20T10:00:00+11:00", "is_pinned": False, "is_answered": True, "user_id": 5,
        **extra,
    }


USER_RESPONSE = {
    "user": {"id": 5, "name": "Student Name", "email": "student@example.edu"},
    "courses": [
        {"course": {"id": 101, "code": "CS 61A", "name": "Structure and Interpretation", "status": "active"},
         "role": {"role": "student"}},
        {"course": {"id": 102, "code": "OLD 1", "name": "Archived", "status": "archived"}, "role": {}},
        {"course": {"id": "103", "code": "BAD", "name": "String id", "status": "active"}, "role": {}},
        {"course": "not a dict"},
        {"course": {"id": 104, "status": "active"}, "role": {}},
    ],
}

THREAD_RESPONSE = {
    "thread": {
        "id": 900, "course_id": 101, "number": 12, "type": "question", "title": "Recursion question",
        "category": "Lectures", "created_at": "2026-11-21T09:00:00Z", "accepted_id": 32,
        "document": "How does the base case work?\n\nSee lecture 5.",
        "content": "<document><paragraph>ignored</paragraph></document>",
        "answers": [
            {"id": 31, "user_id": 7, "document": "", "is_endorsed": True, "is_anonymous": False,
             "content": "<document version=\"2.0\"><paragraph>Check <bold>n == 0</bold> &amp; return.</paragraph>"
                        "<list style=\"bullet\"><list-item><paragraph>one</paragraph></list-item></list></document>",
             "created_at": "2026-11-21T10:00:00Z", "comments": [{"id": 1, "document": "nested reply"}]},
            {"id": 32, "user_id": 8, "document": "Anonymous answer", "is_anonymous": True,
             "created_at": "2026-11-21T11:00:00Z"},
            {"id": 33, "user_id": 99, "document": "Unknown author", "is_endorsed": "yes"},
            "not a dict",
        ],
        "comments": [{"id": 40, "document": "a comment"}],
    },
    "users": [
        {"id": 7, "name": "Tutor Name", "course_role": "staff", "role": "user", "avatar": "x"},
        {"id": 8, "name": "Hidden", "course_role": "student"},
    ],
}


class EdClientTests(unittest.TestCase):
    def setUp(self):
        self.client = EdClient(TOKEN, "us")
        self.client.opener = Mock()

    def requests(self) -> list[Request]:
        return [call.args[0] for call in self.client.opener.open.call_args_list]

    def test_courses_sends_bearer_token_to_fixed_origin_and_keeps_only_active(self):
        self.client.opener.open.return_value = response(USER_RESPONSE)
        self.assertEqual(self.client.courses(), [
            {"id": 101, "code": "CS 61A", "name": "Structure and Interpretation"},
            {"id": 104, "code": None, "name": "Course 104"},
        ])
        (request,) = self.requests()
        self.assertEqual(request.full_url, "https://us.edstem.org/api/user")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, request.full_url)
        self.assertEqual(self.client.opener.open.call_args.kwargs["timeout"], 15)

    def test_region_selects_origin_and_web_links(self):
        for region, origin in (("eu", "https://eu.edstem.org"), (" AU ", "https://au.edstem.org"),
                               ("", "https://us.edstem.org")):
            with self.subTest(region=region):
                client = EdClient(TOKEN, region)
                client.opener = Mock()
                client.opener.open.return_value = response({"threads": [thread_record(1)]})
                (thread,) = client.threads(5, 1)
                self.assertTrue(client.opener.open.call_args.args[0].full_url.startswith(f"{origin}/api/courses/5/"))
                self.assertEqual(thread["url"], f"https://edstem.org/{client.region}/courses/5/discussion/1")

    def test_rejects_bad_region_and_token_without_echoing_them(self):
        for region in ("ca", "us.evil.example", "https://us.edstem.org"):
            with self.subTest(region=region):
                with self.assertRaisesRegex(ValueError, "ED_REGION must be one of") as caught:
                    EdClient(TOKEN, region)
                self.assertNotIn(TOKEN, str(caught.exception))
        for token in ("", "   ", "abc\r\nX-Injected: 1", "a b", "tok\x00en"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(ValueError, "^ED_API_TOKEN must be set$"):
                    EdClient(token, "us")

    def test_redirects_are_rejected(self):
        client = EdClient(TOKEN, "us")
        handler = next(h for h in client.opener.handlers if type(h).__name__ == "RejectRedirects")
        request = Request("https://us.edstem.org/api/user", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/"))

    def test_threads_use_offset_pagination_newest_first_and_cap_at_100(self):
        pages = [
            response({"threads": [thread_record(i) for i in range(1000, 950, -1)]}),
            response({"threads": [thread_record(i) for i in range(950, 900, -1)]}),
        ]
        self.client.opener.open.side_effect = pages
        threads = self.client.threads(5, 500)
        self.assertEqual(len(threads), 100)
        self.assertEqual(threads[0]["id"], 1000)
        queries = [parse_qs(urlsplit(r.full_url).query) for r in self.requests()]
        self.assertEqual(queries, [
            {"limit": ["50"], "offset": ["0"], "sort": ["new"]},
            {"limit": ["50"], "offset": ["50"], "sort": ["new"]},
        ])
        for request in self.requests():
            self.assertEqual(urlsplit(request.full_url).netloc, "us.edstem.org")
            self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")

    def test_threads_stop_on_short_page_dedupe_and_normalize(self):
        self.client.opener.open.side_effect = [
            response({"threads": [thread_record(3), thread_record(3), {"title": "no id"}, {"id": True},
                                  thread_record(2, title=7, is_pinned="yes", created_at="bad", number="x")]}),
        ]
        threads = self.client.threads(5, 20)
        self.client.opener.open.assert_called_once()
        self.assertEqual(threads, [
            {"id": 3, "number": 3, "title": "Thread 3", "type": "question", "category": "Homework",
             "created_at": "2026-11-19T23:00:00Z", "is_pinned": False, "is_answered": True,
             "url": "https://edstem.org/us/courses/5/discussion/3"},
            {"id": 2, "number": None, "title": "Untitled thread", "type": "question", "category": "Homework",
             "created_at": None, "is_pinned": False, "is_answered": True,
             "url": "https://edstem.org/us/courses/5/discussion/2"},
        ])

    def test_small_limit_requests_one_page_of_that_size(self):
        self.client.opener.open.return_value = response({"threads": [thread_record(1), thread_record(2)]})
        self.assertEqual([t["id"] for t in self.client.threads(5, 2)], [1, 2])
        self.assertIn("limit=2&offset=0", self.requests()[0].full_url)

    def test_thread_detail_text_answers_and_privacy(self):
        self.client.opener.open.return_value = response(THREAD_RESPONSE)
        thread = self.client.thread(900)
        self.assertEqual(self.requests()[0].full_url, "https://us.edstem.org/api/threads/900?view=1")
        self.assertEqual(thread["text"], "How does the base case work?\n\nSee lecture 5.")
        self.assertEqual(thread["url"], "https://edstem.org/us/courses/101/discussion/900")
        self.assertEqual(thread["answers"], [
            {"author_role": "staff", "text": "Check n == 0 & return.\n\none", "endorsed": True,
             "accepted": False, "created_at": "2026-11-21T10:00:00Z"},
            {"author_role": None, "text": "Anonymous answer", "endorsed": False, "accepted": True,
             "created_at": "2026-11-21T11:00:00Z"},
            {"author_role": None, "text": "Unknown author", "endorsed": False, "accepted": False,
             "created_at": None},
        ])
        dumped = json.dumps(thread)
        for private in ("Tutor Name", "Hidden", "Student Name", "avatar"):
            self.assertNotIn(private, dumped)

    def test_thread_answers_are_capped(self):
        detail = {"thread": {"id": 1, "course_id": 2, "answers": [{"id": i, "document": str(i)} for i in range(1, 40)]}}
        self.client.opener.open.return_value = response(detail)
        thread = self.client.thread(1)
        self.assertEqual(len(thread["answers"]), 20)
        self.assertEqual((thread["title"], thread["text"]), ("Untitled thread", ""))

    def test_rejects_unexpected_shapes(self):
        cases = [
            (lambda: self.client.courses(), [1, 2], "unexpected user response"),
            (lambda: self.client.courses(), {"courses": {"course": {}}}, "unexpected user response"),
            (lambda: self.client.courses(), {"courses": [1]}, "unexpected user response"),
            (lambda: self.client.threads(5), {"threads": None}, "unexpected threads response"),
            (lambda: self.client.threads(5), {"threads": ["x"]}, "unexpected threads response"),
            (lambda: self.client.thread(9), {"thread": []}, "unexpected thread response"),
            (lambda: self.client.thread(9), {"thread": {"id": "9"}}, "unexpected thread response"),
            (lambda: self.client.thread(9), {"thread": {"id": 9, "answers": {}}}, "unexpected thread response"),
        ]
        for call, body, message in cases:
            with self.subTest(body=body):
                self.client.opener.open.return_value = response(body)
                with self.assertRaisesRegex(ValueError, message):
                    call()
        self.client.opener.open.return_value = response("not json")
        with self.assertRaises(json.JSONDecodeError):
            self.client.courses()

    def test_rejects_invalid_ids_and_limits_before_any_request(self):
        for bad in (0, -1, True, "5"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    self.client.threads(bad)
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    self.client.thread(bad)
                if bad != "5":
                    with self.assertRaisesRegex(ValueError, "limit must be positive"):
                        self.client.threads(5, bad)
        self.client.opener.open.assert_not_called()

    def test_xml_content_to_text(self):
        content = (
            '<!DOCTYPE x [<!ENTITY a "aaaaaaaa">]><document version="2.0"><heading level="1">Title</heading>'
            "<paragraph>Line &lt;one&gt; &a;<!-- note --></paragraph><paragraph></paragraph><pre>  code\n  more</pre></document>"
        )
        self.assertEqual(xml_to_text(content), "Title\n\nLine <one> &a;\n\n  code\n  more")
        self.assertEqual(body_text({"document": 5, "content": None}), "")


class CliTests(unittest.TestCase):
    def run_cli(self, argv, env):
        environment = {"ED_API_TOKEN": "", "ED_REGION": "", "CANVAS_BASE_URL": "", "CANVAS_API_TOKEN": "", **env}
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with patch.dict(os.environ, environment), patch.object(cli, "load_env_file") as load, \
                redirect_stdout(out), redirect_stderr(err):
            try:
                cli.main(argv)
            except SystemExit as exit_:
                code = exit_.code
        if argv[0] == "ed" and code != 2:  # argparse usage errors exit before loading
            load.assert_called_once()
        return code, out.getvalue(), err.getvalue()

    def test_ed_without_token_exits_with_setup_message(self):
        code, out, err = self.run_cli(["ed", "courses"], {})
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "ED_API_TOKEN must be set.\n")
        code, _, err = self.run_cli(["ed", "threads", "5"], {"ED_API_TOKEN": TOKEN, "ED_REGION": "ca"})
        self.assertEqual((code, err), (1, "ED_REGION must be one of us, eu or au.\n"))

    def test_ed_network_errors_are_generic_and_never_echo_the_token(self):
        errors = [
            (HTTPError(f"https://us.edstem.org/api/user?t={TOKEN}", 401, f"bad {TOKEN}", None, None),
             "Ed request failed (HTTP 401).\n"),
            (URLError(f"refused {TOKEN}"), "Could not reach Ed.\n"),
            (TimeoutError(TOKEN), "Could not reach Ed.\n"),
            (json.JSONDecodeError(TOKEN, "doc", 0), "Ed returned invalid JSON.\n"),
            (ValueError("Ed returned an unexpected user response"), "Ed returned an unexpected user response.\n"),
        ]
        for error, message in errors:
            with self.subTest(error=type(error).__name__):
                with patch.object(EdClient, "courses", side_effect=error):
                    code, out, err = self.run_cli(["ed", "courses"], {"ED_API_TOKEN": TOKEN})
                self.assertEqual((code, out, err), (1, "", message))

    def test_ed_threads_prints_json(self):
        with patch.object(EdClient, "threads", return_value=[{"id": 1}]) as threads:
            code, out, _ = self.run_cli(["ed", "threads", "5", "--limit", "3"], {"ED_API_TOKEN": TOKEN})
        self.assertEqual((code, json.loads(out)), (0, [{"id": 1}]))
        threads.assert_called_once_with(5, 3)
        code, _, err = self.run_cli(["ed", "threads", "5", "--limit", "101"], {"ED_API_TOKEN": TOKEN})
        self.assertEqual(code, 2)
        self.assertIn("between 1 and 100", err)

    def test_canvas_subcommand_is_unchanged(self):
        code, _, err = self.run_cli(["canvas", "123"], {})
        self.assertEqual((code, err), (1, "CANVAS_BASE_URL must be an HTTPS origin.\n"))
        with patch.object(cli.CanvasClient, "assignments", return_value=iter([{"id": 1}])):
            code, out, _ = self.run_cli(["canvas", "123"], {
                "CANVAS_BASE_URL": "https://canvas.example.edu", "CANVAS_API_TOKEN": "t",
            })
        self.assertEqual((code, json.loads(out)), (0, [{"id": 1}]))


if __name__ == "__main__":
    unittest.main()
