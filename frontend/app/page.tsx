import NextLink from "next/link";

import {
  getCanvasStatus,
  getCourses,
  getHealth,
  getNotifications,
  getUpcoming,
  type CanvasStatus,
  type Course,
} from "./_lib/api";
import { parseDate, plural } from "./_lib/format";
import { SyncPanel } from "./components/SyncPanel";
import {
  BackendDown,
  DateTime,
  EmptyState,
  ItemCard,
  SiteHeader,
} from "./components/ui";

export const dynamic = "force-dynamic";

function CanvasStatusBox({ status }: { status: CanvasStatus | null }) {
  const now = new Date();
  if (!status) return null;
  const canSync = status.configured || status.demo;
  return (
    <section className="status-box" aria-labelledby="canvas-status-heading">
      <div className="status-text">
        <h2 id="canvas-status-heading" className="status-heading">
          Canvas
          {status.demo ? <span className="badge badge-demo">Demo mode</span> : null}
        </h2>
        {!canSync ? (
          <p className="muted">
            Canvas is not configured. Set <code>CANVAS_BASE_URL</code> and{" "}
            <code>CANVAS_API_TOKEN</code> in the backend environment, or set{" "}
            <code>CANVAS_DEMO=1</code> to try sample data. See the README.
          </p>
        ) : status.last_synced_at ? (
          <p className="muted">
            Last synced <DateTime value={status.last_synced_at} now={now} />
          </p>
        ) : (
          <p className="muted">Not synced yet.</p>
        )}
        {status.syncing ? <p className="muted">A sync is running…</p> : null}
      </div>
      <SyncPanel
        disabled={!canSync}
        disabledReason={!canSync ? "Configure Canvas to enable syncing." : undefined}
      />
    </section>
  );
}

function CourseCard({ course, now }: { course: Course; now: Date }) {
  const nextDue = parseDate(course.next_due_at);
  return (
    <li>
      <NextLink href={`/courses/${course.id}`} className="course-card">
        <span className="course-card-name">{course.name}</span>
        {course.course_code && course.course_code !== course.name ? (
          <span className="course-card-code">{course.course_code}</span>
        ) : null}
        <span className="course-card-stats">
          <span>{plural(course.open_count, "open task")}</span>
          {course.unread_count ? (
            <span className="unread-text">{course.unread_count} unread</span>
          ) : null}
        </span>
        <span className="course-card-due">
          {nextDue ? (
            <DateTime value={course.next_due_at} prefix="Next due" now={now} />
          ) : (
            "Nothing due"
          )}
        </span>
      </NextLink>
    </li>
  );
}

export default async function HomePage() {
  const now = new Date();
  const [healthy, statusResult, upcomingResult, coursesResult, notificationsResult] =
    await Promise.all([
      getHealth(),
      getCanvasStatus(),
      getUpcoming(10),
      getCourses(),
      getNotifications({ unreadOnly: true, limit: 1 }),
    ]);

  const status = statusResult.ok ? statusResult.data : null;
  const unreadCount = notificationsResult.ok ? notificationsResult.data.unread_count : null;
  const backendError = !statusResult.ok
    ? statusResult.message
    : !upcomingResult.ok
      ? upcomingResult.message
      : !coursesResult.ok
        ? coursesResult.message
        : null;

  const upcoming = upcomingResult.ok ? upcomingResult.data.upcoming : [];
  const overdue = upcomingResult.ok ? upcomingResult.data.overdue : [];
  const courses = coursesResult.ok ? coursesResult.data.courses : [];
  const neverSynced = status !== null && !status.last_synced_at && courses.length === 0;
  const [current, ...rest] = upcoming;

  return (
    <>
      <SiteHeader unreadCount={unreadCount} healthy={healthy} />
      <main className="page">
        <div className="page-title-row">
          <h1>Dashboard</h1>
          {unreadCount !== null ? (
            <NextLink href="/notifications" className="unread-link">
              {unreadCount === 0
                ? "No unread notifications"
                : `${plural(unreadCount, "unread notification")}`}
            </NextLink>
          ) : null}
        </div>

        {backendError ? <BackendDown message={backendError} /> : null}
        <CanvasStatusBox status={status} />

        {neverSynced ? (
          <EmptyState title="Nothing here yet">
            <p>Run your first sync to pull courses, assignments and announcements from Canvas.</p>
          </EmptyState>
        ) : null}

        {!neverSynced && upcomingResult.ok ? (
          <>
            <section aria-labelledby="up-next-heading" className="section">
              <h2 id="up-next-heading">Up next</h2>
              {current ? (
                <>
                  <p className="eyebrow">Current task</p>
                  <ItemCard item={current} now={now} featured headingLevel={3} />
                  {rest.length ? (
                    <ul className="item-list" aria-label="Later tasks">
                      {rest.map((item) => (
                        <li key={item.id}>
                          <ItemCard item={item} now={now} />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : (
                <EmptyState title="Nothing upcoming">
                  <p>No open assignments with upcoming due dates.</p>
                </EmptyState>
              )}
            </section>

            {overdue.length ? (
              <section aria-labelledby="overdue-heading" className="section">
                <h2 id="overdue-heading">
                  Overdue <span className="count-pill count-pill-warn">{overdue.length}</span>
                </h2>
                <ul className="item-list">
                  {overdue.map((item) => (
                    <li key={item.id}>
                      <ItemCard item={item} now={now} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        ) : null}

        {!neverSynced && coursesResult.ok ? (
          <section aria-labelledby="courses-heading" className="section">
            <h2 id="courses-heading">Courses</h2>
            {courses.length ? (
              <ul className="course-grid">
                {courses.map((course) => (
                  <CourseCard key={course.id} course={course} now={now} />
                ))}
              </ul>
            ) : (
              <EmptyState title="No courses">
                <p>No active Canvas courses were found in the last sync.</p>
              </EmptyState>
            )}
          </section>
        ) : null}
      </main>
    </>
  );
}
