import NextLink from "next/link";

import {
  getCanvasStatus,
  getEdStatus,
  getToday,
  getUpcoming,
  type Course,
  type Item,
  type Today,
} from "./_lib/api";
import { courseLabel } from "./_lib/course";
import { dayDiff, dayLabel, greeting, longDay, parseDate, plural, serverTimeZone, weekLabel } from "./_lib/format";
import { CourseCard } from "./components/CourseCard";
import { WeightIcon } from "./components/icons";
import { ItemList } from "./components/ItemRow";
import { NotificationRow } from "./components/NotificationRow";
import { SyncControl } from "./components/SyncControl";
import { BackendDown, EmptyState, SectionHeader } from "./components/ui";

const UPDATES_SHOWN = 5;

function capitalize(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "2 things to do today, 1 due tomorrow, 3 updates since yesterday" or "Nothing due today. You’re clear." */
function digestLine(today: Today, dueTomorrow: number): string {
  const todo = today.do_today.length + today.due_today.length;
  const rest: string[] = [];
  if (today.overdue.length) rest.push(`${today.overdue.length} overdue`);
  if (dueTomorrow) rest.push(`${dueTomorrow} due tomorrow`);
  if (today.changes.length) rest.push(plural(today.changes.length, "update") + " since yesterday");
  if (todo) return [plural(todo, "thing") + " to do today", ...rest].join(", ");
  const clear = "Nothing due today. You’re clear.";
  return rest.length ? `${clear} ${capitalize(rest.join(", "))}.` : clear;
}

function HeavyWeek({ week, now }: { week: { start: string; load: number }; now: Date }) {
  const start = parseDate(week.start);
  if (!start) return null;
  const thisWeek = now.getTime() - start.getTime() < 7 * 86_400_000;
  return (
    <aside className="banner" aria-label="Heavy week">
      <span className="banner-icon">
        <WeightIcon />
      </span>
      <p>
        <strong>{thisWeek ? "This is a heavy week." : `Heavy week ahead (week of ${weekLabel(start)}).`}</strong>{" "}
        {plural(week.load, "deadline")} to submit or take. Start the big ones early.
      </p>
    </aside>
  );
}

function ClearState({ next, now }: { next: Item | undefined; now: Date }) {
  const due = next ? parseDate(next.due_at) : null;
  return (
    <EmptyState
      title="Nothing due today. You’re clear."
      icon={
        <svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" focusable="false">
          <circle cx="24" cy="24" r="20" fill="var(--accent-soft)" />
          <path d="M16 24.5l5.5 5.5L33 18.5" fill="none" stroke="var(--accent)" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      }
    >
      {next && due ? (
        <p>
          Next up: <strong>{next.title}</strong>, due {dayLabel(due, now)}.
        </p>
      ) : (
        <p>Enjoy the breathing room.</p>
      )}
    </EmptyState>
  );
}

function Section({
  id,
  title,
  items,
  now,
  labels,
  tone,
}: {
  id: string;
  title: string;
  items: Item[];
  now: Date;
  labels: Map<number, string>;
  tone?: "danger";
}) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={id} className="section">
      <SectionHeader id={id} title={title} count={items.length} tone={tone} />
      <ItemList items={items} now={now} courseLabels={labels} />
    </section>
  );
}

export default async function TodayPage() {
  const now = new Date();
  const [todayResult, upcomingResult, statusResult, edStatusResult] = await Promise.all([
    getToday(serverTimeZone()),
    getUpcoming(50),
    getCanvasStatus(),
    getEdStatus(),
  ]);

  const header = (summary?: string) => (
    <header className="page-head">
      <h1 className="greeting">
        {greeting(now)} <span className="greeting-date">· {longDay(now)}</span>
      </h1>
      {summary ? <p className="digest">{summary}</p> : null}
    </header>
  );

  if (!todayResult.ok) {
    return (
      <div className="page">
        {header()}
        <BackendDown message={todayResult.message} />
      </div>
    );
  }

  const today = todayResult.data;
  const status = statusResult.ok ? statusResult.data : null;
  const edStatus = edStatusResult.ok ? edStatusResult.data : null;
  const canSync = Boolean(status && (status.configured || status.demo)) || Boolean(edStatus && (edStatus.configured || edStatus.demo));
  const neverSynced = !status?.last_synced_at && !edStatus?.last_synced_at && today.courses.length === 0;

  if (neverSynced) {
    return (
      <div className="page">
        {header()}
        <EmptyState title="Let’s bring in your courses">
          <p>
            Sync pulls your assignments, announcements and Ed posts, then plans when to start each one.
          </p>
          {canSync ? (
            <SyncControl disabled={false} variant="primary" />
          ) : (
            <p className="muted">
              Set <code>CANVAS_BASE_URL</code> and <code>CANVAS_API_TOKEN</code> in the backend environment, or{" "}
              <code>CANVAS_DEMO=1</code> to try sample data. See the README.
            </p>
          )}
        </EmptyState>
      </div>
    );
  }

  const labels = new Map<number, string>(today.courses.map(({ course }) => [course.id, courseLabel(course)]));
  const upcoming = upcomingResult.ok ? upcomingResult.data.upcoming : [];
  const dueTomorrow = upcoming.filter((item) => {
    const due = parseDate(item.due_at);
    return due !== null && dayDiff(due, now) === 1;
  }).length;
  const nothingToday = !today.do_today.length && !today.due_today.length && !today.overdue.length;
  const updates = today.changes.slice(0, UPDATES_SHOWN);
  const courses: { course: Course; next: Item[] }[] = today.courses;

  return (
    <div className="page">
      {header(digestLine(today, dueTomorrow))}

      {nothingToday ? (
        <ClearState next={upcoming[0]} now={now} />
      ) : (
        <>
          <Section id="do-today" title="Do today" items={today.do_today} now={now} labels={labels} />
          <Section id="due-today" title="Due today" items={today.due_today} now={now} labels={labels} />
          <Section id="overdue" title="Overdue" items={today.overdue} now={now} labels={labels} tone="danger" />
        </>
      )}

      {updates.length ? (
        <section aria-labelledby="updates" className="section">
          <SectionHeader
            id="updates"
            title="Updates since yesterday"
            count={today.changes.length}
            action={
              <NextLink href="/notifications" className="text-button">
                See all
              </NextLink>
            }
          />
          <ul className="notes is-compact">
            {updates.map((notification) => (
              <NotificationRow key={notification.id} notification={notification} now={now} courseLabels={labels} compact />
            ))}
          </ul>
        </section>
      ) : null}

      {today.heavy_week ? <HeavyWeek week={today.heavy_week} now={now} /> : null}

      {courses.length ? (
        <section aria-labelledby="your-courses" className="section">
          <SectionHeader id="your-courses" title="Your courses" />
          <ul className="course-grid">
            {courses.map(({ course, next }) => (
              <CourseCard key={course.id} course={course} next={next} now={now} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
