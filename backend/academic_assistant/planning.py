"""Plan ("do by") dates and weekly load.

Everything here is a pure function of the item and ``now``, so the plan is
deterministic and every date comes with a short reason the UI can show. The
lead times below are the whole rule; tune them here.
"""

from datetime import datetime, timedelta, timezone

from .canvas_sync import iso, parse_time

READ_LEAD = timedelta(days=1)
QUIZ_LEAD = timedelta(days=1)          # quizzes and discussions
SMALL_SUBMIT_LEAD = timedelta(days=2)  # under BIG_ASSIGNMENT_POINTS, or points unknown
BIG_SUBMIT_LEAD = timedelta(days=4)
BIG_ASSIGNMENT_POINTS = 50
HEAVY_WEEK_LOAD = 3                    # submit/quiz items due in one week
DUE_SOON_REASON = "Due soon: start today"
PAST_DUE_REASON = "Past due: finish today"
# Actions that count towards a week's load.
LOAD_ACTIONS = frozenset({"submit", "quiz"})


def _points(value: float) -> str:
    return f"{value:g}"


def lead_time(action: str | None, points: float | None) -> tuple[timedelta, str]:
    """Return ``(lead, reason)`` for an assignment's action and points."""
    if action == "read":
        return READ_LEAD, "Reading: do it 1 day early"
    if action == "quiz":
        return QUIZ_LEAD, "Quiz: prepare 1 day early"
    if action == "discussion":
        return QUIZ_LEAD, "Discussion: post 1 day early"
    if points is not None and points >= BIG_ASSIGNMENT_POINTS:
        return BIG_SUBMIT_LEAD, f"Big assignment ({_points(points)} pts): start 4 days early"
    if points is None:
        return SMALL_SUBMIT_LEAD, "Assignment: start 2 days early"
    return SMALL_SUBMIT_LEAD, f"Assignment ({_points(points)} pts): start 2 days early"


def do_by(
    kind: str, action: str | None, due_at: str | None, points: float | None, finished: bool, now: datetime
) -> tuple[str | None, str | None]:
    """Return ``(do_by, reason)`` for an item; both null for announcements, undated or finished items.

    ``do_by`` is the due date minus the lead time, but never earlier than
    ``now``: work whose plan date has passed is due soon (start today), and
    work that is already past due should be finished today.
    """
    due = parse_time(due_at)
    if kind != "assignment" or finished or due is None:
        return None, None
    lead, reason = lead_time(action, points)
    planned = due - lead
    if planned < now:
        return iso(now), PAST_DUE_REASON if due < now else DUE_SOON_REASON
    return iso(planned), reason


def week_start(value: datetime) -> datetime:
    """Monday 00:00 UTC of the week containing ``value``."""
    value = value.astimezone(timezone.utc)
    return (value - timedelta(days=value.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def weeks(items: list[dict], now: datetime, count: int) -> list[dict]:
    """Load per UTC week, starting with the week containing ``now``.

    ``items`` are Item objects; a week's load counts the unfinished submit
    and quiz items due in it (including ones already past due this week).
    """
    first = week_start(now)
    result = []
    for index in range(count):
        start = first + timedelta(weeks=index)
        lo, hi = iso(start), iso(start + timedelta(weeks=1))
        ids = [
            item["id"] for item in sorted(items, key=lambda item: (item["due_at"] or "", item["id"]))
            if item["kind"] == "assignment" and not item["finished"] and item["action"] in LOAD_ACTIONS
            and item["due_at"] is not None and lo <= item["due_at"] < hi
        ]
        result.append({"start": lo, "load": len(ids), "heavy": len(ids) >= HEAVY_WEEK_LOAD, "items": ids})
    return result
