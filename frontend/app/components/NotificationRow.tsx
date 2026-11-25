import NextLink from "next/link";

import type { Notification } from "../_lib/api";
import { edCourseLabel } from "../_lib/course";
import { dayTimeLabel, fullDateTime, parseDate, shortAgo } from "../_lib/format";
import { markRead } from "../actions";
import { CheckIcon } from "./icons";
import { CourseDot, ExternalLink } from "./ui";

function typeLabel(notification: Notification): string {
  switch (notification.type) {
    case "new_announcement":
      return "New announcement";
    case "new_assignment":
      return "New assignment";
    case "due_date_changed":
      return notification.item?.kind === "assignment" && !notification.due_at && !notification.item.due_at
        ? "Due date removed"
        : "Due date changed";
    case "assignment_updated":
      return "Assignment updated";
    case "ed_announcement":
      return "Ed announcement";
    default:
      return "Update";
  }
}

/** Where the notification points: its course page anchor, an external link, and the course. */
function target(notification: Notification, courseLabels: Map<number, string>) {
  const item = notification.item;
  if (item) {
    return {
      title: item.title,
      href: `/courses/${item.course_id}#item-${item.id}`,
      external: item.html_url,
      externalLabel: "Open in Canvas",
      course: { id: item.course_id, source: "canvas" as const, label: courseLabels.get(item.course_id) ?? item.course_name },
    };
  }
  const thread = notification.ed_thread;
  if (!thread) return null;
  const edCourse = notification.ed_course;
  const canvasId = edCourse?.canvas_course_id ?? null;
  return {
    title: thread.title,
    // A matched Ed course is shown on its Canvas course page.
    href: `${canvasId ? `/courses/${canvasId}` : `/ed/${thread.ed_course_id}`}#ed-thread-${thread.id}`,
    external: thread.url,
    externalLabel: "Open in Ed",
    course: canvasId
      ? { id: canvasId, source: "canvas" as const, label: courseLabels.get(canvasId) ?? (edCourse ? edCourseLabel(edCourse) : "Ed") }
      : { id: thread.ed_course_id, source: "ed" as const, label: edCourse ? edCourseLabel(edCourse) : "Ed course" },
  };
}

/**
 * One notification in the item-row style: unread dot, the item's title as a
 * link to its course page, then the kind of change, course and due date.
 * ``compact`` (the Today page) hides the mark-read and external buttons.
 */
export function NotificationRow({
  notification,
  now,
  courseLabels,
  compact = false,
}: {
  notification: Notification;
  now: Date;
  courseLabels: Map<number, string>;
  compact?: boolean;
}) {
  const unread = notification.read_at === null;
  const created = parseDate(notification.created_at);
  const due = notification.item?.kind === "assignment" ? parseDate(notification.due_at) : null;
  const where = target(notification, courseLabels);
  return (
    <li className={`note${unread ? " is-unread" : ""}`}>
      <span className="note-dot" aria-hidden="true" />
      <div className="note-content">
        <p className="note-title">
          <span className="visually-hidden">{unread ? "Unread: " : ""}</span>
          {where ? (
            <NextLink href={where.href} title={notification.message}>
              {where.title}
            </NextLink>
          ) : (
            notification.message
          )}
        </p>
        <p className="note-meta">
          <span>{typeLabel(notification)}</span>
          {where ? (
            <span className="row-course">
              <CourseDot id={where.course.id} source={where.course.source} />
              {where.course.label}
            </span>
          ) : null}
          {due ? (
            <span>
              Due{" "}
              <time dateTime={due.toISOString()} title={fullDateTime(due)}>
                {dayTimeLabel(due, now)}
              </time>
            </span>
          ) : null}
        </p>
      </div>
      <div className="note-side">
        {created ? (
          <time className="note-time" dateTime={created.toISOString()} title={fullDateTime(created)}>
            {shortAgo(created, now)}
          </time>
        ) : null}
        {!compact ? (
          <span className="note-actions">
            {where ? (
              <ExternalLink href={where.external} className="icon-button" icon>
                <span className="visually-hidden">
                  {where.externalLabel}: {where.title}
                </span>
              </ExternalLink>
            ) : null}
            {unread ? (
              <form action={markRead}>
                <input type="hidden" name="id" value={notification.id} />
                <button type="submit" className="icon-button" title="Mark read">
                  <CheckIcon size={18} />
                  <span className="visually-hidden">Mark read: {where?.title ?? notification.message}</span>
                </button>
              </form>
            ) : null}
          </span>
        ) : null}
      </div>
    </li>
  );
}
