import type { Metadata } from "next";
import NextLink from "next/link";
import { notFound } from "next/navigation";

import { getCourse, getCourseEd, getCourseItems, isFinished, type Item } from "../../_lib/api";
import { courseHue, courseLabel, courseTitle } from "../../_lib/course";
import { dayTimeLabel, formatRelative, parseDate } from "../../_lib/format";
import { ArrowLeftIcon } from "../../components/icons";
import { ItemList } from "../../components/ItemRow";
import { AnnouncementCard, EdThreadList } from "../../components/PostCard";
import { BackendDown, EmptyState, ExternalLink, SectionHeader } from "../../components/ui";

function parseCourseId(id: string): number | null {
  return /^\d{1,15}$/.test(id) && Number(id) > 0 ? Number(id) : null;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const courseId = parseCourseId((await params).id);
  const result = courseId ? await getCourse(courseId) : null;
  return { title: result?.ok ? courseLabel(result.data) : "Course" };
}

/** What's left first: by do-by date, then due date; undated work last. */
function byPlan(a: Item, b: Item): number {
  const key = (item: Item) => [item.do_by ?? item.due_at ?? "￿", item.due_at ?? "￿"];
  const [a1, a2] = key(a);
  const [b1, b2] = key(b);
  return a1.localeCompare(b1) || a2.localeCompare(b2) || a.id - b.id;
}

function BackLink() {
  return (
    <NextLink href="/courses" className="back-link">
      <ArrowLeftIcon size={16} />
      Courses
    </NextLink>
  );
}

export default async function CoursePage({ params }: { params: Promise<{ id: string }> }) {
  const courseId = parseCourseId((await params).id);
  if (courseId === null) notFound();
  const now = new Date();

  const [courseResult, assignmentsResult, announcementsResult, edResult] = await Promise.all([
    getCourse(courseId),
    getCourseItems(courseId, "assignment"),
    getCourseItems(courseId, "announcement"),
    getCourseEd(courseId),
  ]);
  if (!courseResult.ok && courseResult.status === 404) notFound();

  if (!courseResult.ok) {
    return (
      <div className="page">
        <BackLink />
        <header className="page-head">
          <h1>Course</h1>
        </header>
        <BackendDown message={courseResult.message} />
      </div>
    );
  }

  const course = courseResult.data;
  const assignments = assignmentsResult.ok ? assignmentsResult.data.items : [];
  const left = assignments.filter((item) => !isFinished(item)).sort(byPlan);
  const done = assignments.filter(isFinished);
  const announcements = announcementsResult.ok ? announcementsResult.data.items : [];
  // Shown only for a course with a matched Ed course; an Ed read error hides it too.
  const ed = edResult.ok && edResult.data.ed_course ? edResult.data : null;
  const nextDue = parseDate(course.next_due_at);
  const synced = parseDate(course.synced_at);

  const overdue = left.filter((item) => {
    const due = parseDate(item.due_at);
    return due !== null && due < now;
  }).length;
  const stats: string[] = [left.length ? `${left.length} left` : "All caught up"];
  if (overdue) stats.push(`${overdue} overdue`);
  if (nextDue) stats.push(`next due ${dayTimeLabel(nextDue, now)}`);
  if (course.unread_count) stats.push(`${course.unread_count} unread`);
  if (synced) stats.push(`synced ${formatRelative(synced, now)}`);

  return (
    <div className="page">
      <BackLink />
      <header className="course-hero" data-hue={courseHue(course.id)}>
        <p className="course-hero-code">
          <span className="course-dot" aria-hidden="true" />
          {courseLabel(course)}
        </p>
        <h1>{courseTitle(course)}</h1>
        <p className="course-hero-stats">{stats.join(" · ")}</p>
      </header>

      <section aria-labelledby="left-heading" className="section">
        <SectionHeader id="left-heading" title="What’s left" count={left.length} />
        {!assignmentsResult.ok ? (
          <BackendDown message={assignmentsResult.message} />
        ) : left.length ? (
          <ItemList items={left} now={now} showCourse={false} />
        ) : (
          <EmptyState title="All caught up">
            <p>Nothing left to do in this course.</p>
          </EmptyState>
        )}
      </section>

      {done.length ? (
        <section aria-labelledby="done-heading" className="section">
          <details className="fold">
            <summary>
              <h2 id="done-heading">
                Done<span className="section-count">{done.length}</span>
              </h2>
            </summary>
            <ItemList items={done} now={now} showCourse={false} />
          </details>
        </section>
      ) : null}

      <section aria-labelledby="announcements-heading" className="section">
        <SectionHeader id="announcements-heading" title="Announcements" />
        {!announcementsResult.ok ? (
          <BackendDown message={announcementsResult.message} />
        ) : announcements.length ? (
          <ul className="posts">
            {announcements.map((item) => (
              <li key={item.id}>
                <AnnouncementCard item={item} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No announcements in the last 60 days." />
        )}
      </section>

      {ed && ed.ed_course ? (
        <section aria-labelledby="ed-heading" className="section">
          <SectionHeader
            id="ed-heading"
            title="Ed Discussion"
            action={
              <ExternalLink href={ed.ed_course.url} className="text-button">
                Open Ed
              </ExternalLink>
            }
          />
          <EdThreadList threads={ed.threads} />
        </section>
      ) : null}
    </div>
  );
}
