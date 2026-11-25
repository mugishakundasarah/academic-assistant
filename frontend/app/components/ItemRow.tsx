import NextLink from "next/link";

import { isFinished, type Item } from "../_lib/api";
import { dayDiff, dayLabel, dayPhrase, dayTimeLabel, fullDateTime, parseDate, points, timeLabel } from "../_lib/format";
import { CalendarIcon } from "./icons";
import { ItemRowShell } from "./ItemRowShell";
import { CollapsibleText, CourseDot, ExternalLink, LinkChips, TypeChip } from "./ui";

function When({ item, now }: { item: Item; now: Date }) {
  const due = parseDate(item.due_at);
  const doBy = parseDate(item.do_by);
  const finished = isFinished(item);
  if (!due) {
    return <span className="when"><span className="when-main is-quiet">No due date</span></span>;
  }
  const dueTime = (
    <time dateTime={due.toISOString()} title={fullDateTime(due)}>
      {dayTimeLabel(due, now)}
    </time>
  );
  if (finished) {
    return <span className="when"><span className="when-sub">due {dueTime}</span></span>;
  }
  if (due < now) {
    // The section (or the red ring) already says overdue; lead with when it was due.
    return (
      <span className="when is-overdue">
        <span className="when-main">
          <span className="visually-hidden">Overdue: </span>
          Due {dayPhrase(due, now)}
        </span>
        <span className="when-sub">
          <time dateTime={due.toISOString()} title={fullDateTime(due)}>{timeLabel(due)}</time>
        </span>
      </span>
    );
  }
  if (!doBy || dayDiff(doBy, now) >= dayDiff(due, now)) {
    // Planned for the day it is due: lead with the due day.
    return (
      <span className="when">
        <span className="when-main">Due {dayPhrase(due, now)}</span>
        <span className="when-sub">
          <time dateTime={due.toISOString()} title={fullDateTime(due)}>{timeLabel(due)}</time>
        </span>
      </span>
    );
  }
  const planDay = dayDiff(doBy, now);
  const plan = planDay <= 0 ? "Do today" : planDay === 1 ? "Do tomorrow" : `Do by ${dayLabel(doBy, now)}`;
  return (
    <span className="when">
      <span className="when-main" title={item.do_by_reason ?? undefined}>{plan}</span>
      <span className="when-sub">due {dueTime}</span>
    </span>
  );
}

/**
 * One assignment: checkbox, title, type chip, course and dates. Clicking the
 * row expands its details inline (plan reason, instructions, files, Canvas).
 */
export function ItemRow({
  item,
  now,
  courseLabel,
  showCourse = true,
}: {
  item: Item;
  now: Date;
  /** The course code to show; defaults to the item's course name. */
  courseLabel?: string;
  showCourse?: boolean;
}) {
  const finished = isFinished(item);
  const due = parseDate(item.due_at);
  const overdue = !finished && due !== null && due < now;
  const facts: string[] = [];
  if (due) facts.push(`Due ${fullDateTime(due)}`);
  if (item.points_possible !== null && item.points_possible !== undefined) facts.push(points(item.points_possible));
  if (item.completed) facts.push("Completed in Canvas");
  else if (item.done) facts.push("Marked done here");

  return (
    <ItemRowShell
      itemId={item.id}
      title={item.title}
      done={Boolean(item.done)}
      completed={item.completed}
      overdue={overdue}
    >
      <details className="row-details">
        <summary className="row-summary">
          <span className="row-text">
            <span className="row-title">{item.title}</span>
            <span className="row-meta">
              <TypeChip item={item} />
              {showCourse ? (
                <span className="row-course">
                  <CourseDot id={item.course_id} />
                  {courseLabel ?? item.course_name}
                </span>
              ) : null}
              {item.missing && !finished ? <span className="row-flag">Missing</span> : null}
            </span>
          </span>
          <When item={item} now={now} />
        </summary>
        <div className="row-body">
          {facts.length ? <p className="row-facts">{facts.join(" · ")}</p> : null}
          {item.do_by_reason && !finished ? (
            <p className="row-plan">
              <CalendarIcon size={16} />
              <span>{item.do_by_reason}</span>
            </p>
          ) : null}
          <CollapsibleText text={item.text} label="Show instructions" />
          <LinkChips links={item.links} />
          <div className="row-actions">
            <ExternalLink href={item.html_url} className="text-button">
              Open in Canvas
            </ExternalLink>
            {showCourse ? (
              <NextLink href={`/courses/${item.course_id}`} className="text-button">
                Go to course
              </NextLink>
            ) : null}
          </div>
        </div>
      </details>
    </ItemRowShell>
  );
}

/** A list of item rows on one surface. */
export function ItemList({
  items,
  now,
  courseLabels,
  showCourse = true,
  label,
}: {
  items: Item[];
  now: Date;
  courseLabels?: Map<number, string>;
  showCourse?: boolean;
  label?: string;
}) {
  return (
    <ul className="rows" aria-label={label}>
      {items.map((item) => (
        <ItemRow
          key={item.id}
          item={item}
          now={now}
          showCourse={showCourse}
          courseLabel={courseLabels?.get(item.course_id)}
        />
      ))}
    </ul>
  );
}
