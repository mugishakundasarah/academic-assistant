import NextLink from "next/link";

import type { Course, Item } from "../_lib/api";
import { courseHue, courseLabel, courseTitle } from "../_lib/course";
import { dayDiff, dayLabel, dayPhrase, dayTimeLabel, parseDate } from "../_lib/format";
import { CheckIcon } from "./icons";

/** Within this many days (or overdue, or planned for this window) an item counts as "this week". */
const WEEK_DAYS = 7;

function soon(item: Item, now: Date): boolean {
  const due = parseDate(item.due_at);
  const doBy = parseDate(item.do_by);
  return (due !== null && dayDiff(due, now) < WEEK_DAYS) || (doBy !== null && dayDiff(doBy, now) < WEEK_DAYS);
}

function MiniWhen({ item, now }: { item: Item; now: Date }) {
  const due = parseDate(item.due_at);
  const doBy = parseDate(item.do_by);
  if (!due) return <span className="mini-when">No due date</span>;
  if (due < now) return <span className="mini-when is-overdue">Overdue</span>;
  const planDay = doBy ? dayDiff(doBy, now) : null;
  if (planDay !== null && planDay < dayDiff(due, now)) {
    const plan = planDay <= 0 ? "Do today" : planDay === 1 ? "Do tomorrow" : `Do by ${dayLabel(doBy!, now)}`;
    return (
      <span className="mini-when">
        {plan} <span className="mini-sep">·</span> due {dayPhrase(due, now)}
      </span>
    );
  }
  return <span className="mini-when">Due {dayTimeLabel(due, now)}</span>;
}

/**
 * A course on the Today page and the Courses page: colour rail, code and
 * name, then its next one or two items, or a quiet all-clear.
 */
export function CourseCard({ course, next, now }: { course: Course; next: Item[]; now: Date }) {
  const thisWeek = next.filter((item) => soon(item, now));
  const later = thisWeek.length === 0 ? next[0] : undefined;
  const laterDue = later ? parseDate(later.due_at) : null;
  return (
    <li>
      <NextLink href={`/courses/${course.id}`} className="course-card" data-hue={courseHue(course.id)}>
        <span className="course-card-head">
          <span className="course-card-code">{courseLabel(course)}</span>
          {course.unread_count ? (
            <span className="course-card-unread">
              {course.unread_count} new<span className="visually-hidden"> unread</span>
            </span>
          ) : null}
        </span>
        <span className="course-card-title">{courseTitle(course)}</span>
        {thisWeek.length ? (
          <span className="course-card-items">
            {thisWeek.map((item) => (
              <span className="mini" key={item.id}>
                <span className="mini-title">{item.title}</span>
                <MiniWhen item={item} now={now} />
              </span>
            ))}
          </span>
        ) : (
          <span className="course-card-clear">
            <span className="clear-line">
              <CheckIcon size={16} />
              Nothing due this week
            </span>
            {later ? (
              <span className="clear-next">
                Next: {later.title}
                {laterDue ? ` · ${dayLabel(laterDue, now)}` : ""}
              </span>
            ) : null}
          </span>
        )}
      </NextLink>
    </li>
  );
}
