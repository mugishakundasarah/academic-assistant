"""Local read-only import preview."""

import argparse
import json
import os
from http.client import HTTPException
from urllib.error import HTTPError, URLError

from ..env import load_env_file
from .canvas import CanvasClient
from .ed import MAX_THREADS, EdClient


def canvas_preview(parser: argparse.ArgumentParser, args: argparse.Namespace):
    try:
        client = CanvasClient(os.getenv("CANVAS_BASE_URL", ""), os.getenv("CANVAS_API_TOKEN", ""))
        return list(client.assignments(args.course_id))
    except HTTPError as error:
        parser.exit(1, f"Canvas request failed (HTTP {error.code}).\n")
    except (URLError, TimeoutError):
        parser.exit(1, "Could not reach Canvas.\n")
    except json.JSONDecodeError:
        parser.exit(1, "Canvas returned invalid JSON.\n")
    except ValueError as error:
        parser.exit(1, f"{error}.\n")


def ed_preview(parser: argparse.ArgumentParser, args: argparse.Namespace):
    # The Ed preview reads backend/.env like the Ed MCP server; real
    # environment variables still win.
    load_env_file()
    try:
        client = EdClient(os.getenv("ED_API_TOKEN", ""), os.getenv("ED_REGION", ""))
        if args.command == "courses":
            return client.courses()
        return client.threads(args.course_id, args.limit)
    except HTTPError as error:
        parser.exit(1, f"Ed request failed (HTTP {error.code}).\n")
    except json.JSONDecodeError:
        parser.exit(1, "Ed returned invalid JSON.\n")
    except ValueError as error:
        # ValueError messages come from the client and never include the token.
        parser.exit(1, f"{error}.\n")
    except (RecursionError, HTTPException):
        parser.exit(1, "Ed returned an unexpected response.\n")
    except OSError:
        # URLError, timeouts, connection and TLS errors.
        parser.exit(1, "Could not reach Ed.\n")


def limit_type(value: str) -> int:
    number = int(value)
    if not 1 <= number <= MAX_THREADS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_THREADS}")
    return number


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    providers = parser.add_subparsers(dest="provider", required=True)
    canvas = providers.add_parser("canvas", help="print a Canvas course's assignments")
    canvas.add_argument("course_id", type=int)
    ed = providers.add_parser("ed", help="print Ed Discussion courses or recent threads")
    commands = ed.add_subparsers(dest="command", required=True)
    commands.add_parser("courses", help="list active Ed courses")
    threads = commands.add_parser("threads", help="list a course's recent threads, newest first")
    threads.add_argument("course_id", type=int)
    threads.add_argument("--limit", type=limit_type, default=20, help=f"1 to {MAX_THREADS} (default 20)")
    args = parser.parse_args(argv)
    records = canvas_preview(parser, args) if args.provider == "canvas" else ed_preview(parser, args)
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
