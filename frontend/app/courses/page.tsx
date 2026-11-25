import type { Metadata } from "next";
import NextLink from "next/link";

import { getEdCourses, getToday } from "../_lib/api";
import { edCourseLabel } from "../_lib/course";
import { serverTimeZone } from "../_lib/format";
import { CourseCard } from "../components/CourseCard";
import { BackendDown, CourseDot, EmptyState, SectionHeader } from "../components/ui";

export const metadata: Metadata = { title: "Courses" };

/** Every course with its next work; the mobile Courses tab and the sidebar heading link here. */
export default async function CoursesPage() {
  const now = new Date();
  const [todayResult, edResult] = await Promise.all([getToday(serverTimeZone()), getEdCourses()]);
  const edOnly = edResult.ok ? edResult.data.courses.filter((course) => course.canvas_course_id === null) : [];

  return (
    <div className="page">
      <header className="page-head">
        <h1>Courses</h1>
      </header>
      {!todayResult.ok ? (
        <BackendDown message={todayResult.message} />
      ) : todayResult.data.courses.length ? (
        <ul className="course-grid">
          {todayResult.data.courses.map(({ course, next }) => (
            <CourseCard key={course.id} course={course} next={next} now={now} />
          ))}
        </ul>
      ) : (
        <EmptyState title="No courses yet">
          <p>
            Courses appear after a <NextLink href="/">sync</NextLink>.
          </p>
        </EmptyState>
      )}

      {edOnly.length ? (
        <section aria-labelledby="ed-only" className="section">
          <SectionHeader id="ed-only" title="Other Ed courses" />
          <ul className="link-rows">
            {edOnly.map((course) => (
              <li key={course.id}>
                <NextLink href={`/ed/${course.id}`} className="link-row">
                  <CourseDot id={course.id} source="ed" />
                  <span className="link-row-main">{edCourseLabel(course)}</span>
                  {course.code && course.name !== course.code ? (
                    <span className="link-row-sub">{course.name}</span>
                  ) : null}
                </NextLink>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
