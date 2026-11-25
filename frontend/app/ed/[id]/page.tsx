import NextLink from "next/link";
import { notFound, redirect } from "next/navigation";

import { getEdCourse, getNotifications } from "../../_lib/api";
import { DateTime, BackendDown, ExternalLink, SiteHeader } from "../../components/ui";
import { EdThreadList } from "../../components/EdThreads";

export const dynamic = "force-dynamic";

/** An Ed course that matches no Canvas course (matched ones show on the Canvas course page). */
export default async function EdCoursePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^\d{1,15}$/.test(id) || Number(id) <= 0) notFound();
  const now = new Date();

  const [result, notificationsResult] = await Promise.all([
    getEdCourse(Number(id)),
    getNotifications({ unreadOnly: true, limit: 1 }),
  ]);
  if (!result.ok && result.status === 404) notFound();
  const unreadCount = notificationsResult.ok ? notificationsResult.data.unread_count : null;

  if (!result.ok || !result.data.ed_course) {
    return (
      <>
        <SiteHeader unreadCount={unreadCount} healthy={!result.ok ? result.status !== null : true} />
        <main className="page">
          <p className="breadcrumb">
            <NextLink href="/">← Dashboard</NextLink>
          </p>
          <h1>Ed course</h1>
          <BackendDown message={result.ok ? "The backend returned an unexpected response." : result.message} />
        </main>
      </>
    );
  }

  const { ed_course: course, threads } = result.data;
  if (course.canvas_course_id !== null) redirect(`/courses/${course.canvas_course_id}`);
  const title = course.code ?? course.name;

  return (
    <>
      <SiteHeader unreadCount={unreadCount} healthy />
      <main className="page">
        <p className="breadcrumb">
          <NextLink href="/">← Dashboard</NextLink>
        </p>
        <header className="course-header">
          <h1>{title}</h1>
          <p className="muted">
            {course.code && course.name !== course.code ? <span>{course.name} · </span> : null}
            Ed Discussion
            {course.synced_at ? (
              <>
                {" · "}
                <DateTime value={course.synced_at} prefix="Synced" now={now} />
              </>
            ) : null}
          </p>
        </header>

        <section aria-labelledby="ed-heading" className="section">
          <div className="section-title-row">
            <h2 id="ed-heading">Staff posts</h2>
            <ExternalLink href={course.url} className="section-link">
              Open Ed course
            </ExternalLink>
          </div>
          <EdThreadList threads={threads} now={now} />
        </section>
      </main>
    </>
  );
}
