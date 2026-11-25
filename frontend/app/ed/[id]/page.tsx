import type { Metadata } from "next";
import NextLink from "next/link";
import { notFound, redirect } from "next/navigation";

import { getEdCourse } from "../../_lib/api";
import { courseHue, edCourseLabel } from "../../_lib/course";
import { formatRelative, parseDate } from "../../_lib/format";
import { ArrowLeftIcon } from "../../components/icons";
import { EdThreadList } from "../../components/PostCard";
import { BackendDown, ExternalLink, SectionHeader } from "../../components/ui";

export const metadata: Metadata = { title: "Ed Discussion" };

function BackLink() {
  return (
    <NextLink href="/courses" className="back-link">
      <ArrowLeftIcon size={16} />
      Courses
    </NextLink>
  );
}

/** An Ed course that matches no Canvas course (matched ones show on the Canvas course page). */
export default async function EdCoursePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d{1,15}$/.test(id) || Number(id) <= 0) notFound();
  const now = new Date();

  const result = await getEdCourse(Number(id));
  if (!result.ok && result.status === 404) notFound();

  if (!result.ok || !result.data.ed_course) {
    return (
      <div className="page">
        <BackLink />
        <header className="page-head">
          <h1>Ed course</h1>
        </header>
        <BackendDown message={result.ok ? "The backend returned an unexpected response." : result.message} />
      </div>
    );
  }

  const { ed_course: course, threads } = result.data;
  if (course.canvas_course_id !== null) redirect(`/courses/${course.canvas_course_id}`);
  const synced = parseDate(course.synced_at);
  const stats = ["Ed Discussion"];
  if (course.code && course.name !== course.code) stats.unshift(course.name);
  if (synced) stats.push(`synced ${formatRelative(synced, now)}`);

  return (
    <div className="page">
      <BackLink />
      <header className="course-hero" data-hue={courseHue(course.id, "ed")}>
        <p className="course-hero-code">
          <span className="course-dot" aria-hidden="true" />
          Ed only
        </p>
        <h1>{edCourseLabel(course)}</h1>
        <p className="course-hero-stats">{stats.join(" · ")}</p>
      </header>

      <section aria-labelledby="ed-heading" className="section">
        <SectionHeader
          id="ed-heading"
          title="Staff posts"
          action={
            <ExternalLink href={course.url} className="text-button">
              Open Ed
            </ExternalLink>
          }
        />
        <EdThreadList threads={threads} />
      </section>
    </div>
  );
}
