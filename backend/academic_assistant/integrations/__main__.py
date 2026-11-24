"""Local read-only import preview."""

import argparse
import json
import os
from urllib.error import HTTPError, URLError

from .canvas import CanvasClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=["canvas"])
    parser.add_argument("course_id", type=int)
    args = parser.parse_args()
    try:
        client = CanvasClient(os.getenv("CANVAS_BASE_URL", ""), os.getenv("CANVAS_API_TOKEN", ""))
        assignments = list(client.assignments(args.course_id))
    except HTTPError as error:
        parser.exit(1, f"Canvas request failed (HTTP {error.code}).\n")
    except (URLError, TimeoutError):
        parser.exit(1, "Could not reach Canvas.\n")
    except json.JSONDecodeError:
        parser.exit(1, "Canvas returned invalid JSON.\n")
    except ValueError as error:
        parser.exit(1, f"{error}.\n")
    print(json.dumps(assignments, indent=2))


if __name__ == "__main__":
    main()
