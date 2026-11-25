import NextLink from "next/link";
import { notFound } from "next/navigation";

import {
  getCourse,
  getCourseEd,
  getCourseItems,
  getNotifications,
  type Item,
} from "../../_lib/api";
import { plural } from "../../_lib/format";
import {
  BackendDown,
  DateTime,
  EmptyState,
  ExternalLink,
  ItemCard,
  LinkList,
  Paragraphs,
  SiteHeader,
} from "../../components/ui";
import { EdThreadList } from "../../components/EdThreads";

export const dynamic = "force-dynamic";

function Announcement({ item, now }: { item: Item; now: Date }) {
  return (
    <article className="announcement" id={`item-${item.id}`}>
      <h3 className="item-title">{item.title}</h3>
      <p className="muted small">
        {item.author ? <span>{item.author} · </span> : null}
        <DateTime value={item.posted_at} prefix="Posted" now={now} />
      </p>
      {item.text ? (
        <Paragraphs text={item.text} />
      ) : (
        <p className="muted">No message text.</p>
      )}
      <LinkList links={item.links} />
      <ExternalLink href={item.html_url} className="canvas-link">
        Open in Canvas
      </ExternalLink>
    </article>
  );
}

export default async function CoursePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^\d{1,15}$/.test(id) || Number(id) <= 0) notFound();
  const courseId = Number(id);
  const now = new Date();

  const [courseResult, assignmentsResult, announcementsResult, notificationsResult, edResult] =
    await Promise.all([
      getCourse(courseId),
      getCourseItems(courseId, "assignment"),
      getCourseItems(courseId, "announcement"),
      getNotifications({ unreadOnly: true, limit: 1 }),
      getCourseEd(courseId),
    ]);

  if (!courseResult.ok && courseResult.status === 404) notFound();
  const unreadCount = notificationsResult.ok ? notificationsResult.data.unread_count : null;

  if (!courseResult.ok) {
    return (
      <>
        <SiteHeader unreadCount={unreadCount} healthy={courseResult.status !== null} />
        <main className="page">
          <p className="breadcrumb">
            <NextLink href="/">← Dashboard</NextLink>
          </p>
          <h1>Course</h1>
          <BackendDown message={courseResult.message} />
        </main>
      </>
    );
  }

  const course = courseResult.data;
  const assignments = assignmentsResult.ok ? assignmentsResult.data.items : [];
  const todo = assignments.filter((item) => !item.completed);
  const done = assignments.filter((item) => item.completed);
  const announcements = announcementsResult.ok ? announcementsResult.data.items : [];
  // Shown only for a course with a matched Ed course; an Ed read error hides it too.
  const ed = edResult.ok && edResult.data.ed_course ? edResult.data : null;

  return (
    <>
      <SiteHeader unreadCount={unreadCount} healthy />
      <main className="page">
        <p className="breadcrumb">
          <NextLink href="/">← Dashboard</NextLink>
        </p>
        <header className="course-header">
          <h1>{course.name}</h1>
          <p className="muted">
            {course.course_code ? <span>{course.course_code} · </span> : null}
            {plural(course.open_count, "open task")}
            {course.unread_count ? ` · ${course.unread_count} unread` : ""}
            {course.synced_at ? (
              <>
                {" · "}
                <DateTime value={course.synced_at} prefix="Synced" now={now} />
              </>
            ) : null}
          </p>
        </header>

        <section aria-labelledby="todo-heading" className="section">
          <h2 id="todo-heading">To do</h2>
          {!assignmentsResult.ok ? (
            <BackendDown message={assignmentsResult.message} />
          ) : todo.length ? (
            <ul className="item-list">
              {todo.map((item) => (
                <li key={item.id}>
                  <ItemCard item={item} now={now} showCourse={false} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="All caught up">
              <p>No open assignments in this course.</p>
            </EmptyState>
          )}
        </section>

        {assignmentsResult.ok && done.length ? (
          <section aria-labelledby="done-heading" className="section">
            <details className="done-details">
              <summary>
                <h2 id="done-heading">Done ({done.length})</h2>
              </summary>
              <ul className="item-list">
                {done.map((item) => (
                  <li key={item.id}>
                    <ItemCard item={item} now={now} showCourse={false} />
                  </li>
                ))}
              </ul>
            </details>
          </section>
        ) : null}

        <section aria-labelledby="announcements-heading" className="section">
          <h2 id="announcements-heading">Announcements</h2>
          {!announcementsResult.ok ? (
            <BackendDown message={announcementsResult.message} />
          ) : announcements.length ? (
            <ul className="item-list">
              {announcements.map((item) => (
                <li key={item.id}>
                  <Announcement item={item} now={now} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No announcements">
              <p>No announcements from the last 60 days.</p>
            </EmptyState>
          )}
        </section>

        {ed && ed.ed_course ? (
          <section aria-labelledby="ed-heading" className="section">
            <div className="section-title-row">
              <h2 id="ed-heading">Ed Discussion</h2>
              <ExternalLink href={ed.ed_course.url} className="section-link">
                Open Ed course
              </ExternalLink>
            </div>
            <EdThreadList threads={ed.threads} now={now} />
          </section>
        ) : null}
      </main>
    </>
  );
}
