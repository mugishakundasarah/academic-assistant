import NextLink from "next/link";
import type { ReactNode } from "react";

import {
  getCanvasStatus,
  getCourses,
  getEdCourses,
  getEdStatus,
  getNotifications,
  type Course,
  type EdCourse,
} from "../_lib/api";
import { courseLabel, courseTitle, edCourseLabel } from "../_lib/course";
import { formatRelative, parseDate } from "../_lib/format";
import { DoneProvider } from "./DoneProvider";
import { AppMark, BellIcon, CoursesIcon, TodayIcon } from "./icons";
import { NavLink } from "./NavLink";
import { SyncControl } from "./SyncControl";
import { CourseDot } from "./ui";

function Badge({ count, label }: { count: number; label: string }) {
  if (!count) return null;
  return (
    <span className="nav-badge">
      {count}
      <span className="visually-hidden"> {label}</span>
    </span>
  );
}

function SidebarCourses({ courses, edCourses }: { courses: Course[]; edCourses: EdCourse[] }) {
  if (courses.length === 0 && edCourses.length === 0) return null;
  return (
    <div className="side-group">
      <NavLink href="/courses" className="side-heading">
        Courses
      </NavLink>
      <ul className="side-list">
        {courses.map((course) => (
          <li key={course.id}>
            <NavLink href={`/courses/${course.id}`} className="nav-item side-course" title={course.name}>
              <CourseDot id={course.id} />
              <span className="side-course-label">
                <span className="side-course-code">{courseLabel(course)}</span>
                <span className="side-course-name">{courseTitle(course)}</span>
              </span>
              {course.open_count ? (
                <span className="side-count">
                  {course.open_count}
                  <span className="visually-hidden"> open</span>
                </span>
              ) : null}
            </NavLink>
          </li>
        ))}
        {edCourses.map((course) => (
          <li key={`ed-${course.id}`}>
            <NavLink href={`/ed/${course.id}`} className="nav-item side-course" title={course.name}>
              <CourseDot id={course.id} source="ed" />
              <span className="side-course-label">
                <span className="side-course-code">{edCourseLabel(course)}</span>
                <span className="side-course-name">Ed only</span>
              </span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The app frame: a sidebar on wide screens; a top bar and a bottom tab bar
 * on narrow ones. Everything here is fetched on the server; the browser
 * only talks to Next.js.
 */
export async function AppShell({ children }: { children: ReactNode }) {
  const now = new Date();
  const [statusResult, edStatusResult, coursesResult, edCoursesResult, unreadResult] = await Promise.all([
    getCanvasStatus(),
    getEdStatus(),
    getCourses(),
    getEdCourses(),
    getNotifications({ unreadOnly: true, limit: 1 }),
  ]);
  const status = statusResult.ok ? statusResult.data : null;
  const edStatus = edStatusResult.ok ? edStatusResult.data : null;
  const courses = coursesResult.ok ? coursesResult.data.courses : [];
  const edOnly = edCoursesResult.ok
    ? edCoursesResult.data.courses.filter((course) => course.canvas_course_id === null)
    : [];
  const unread = unreadResult.ok ? unreadResult.data.unread_count : 0;
  const demo = Boolean(status?.demo);
  const canSync = Boolean(status && (status.configured || status.demo)) || Boolean(edStatus && (edStatus.configured || edStatus.demo));
  const synced = [parseDate(status?.last_synced_at), parseDate(edStatus?.last_synced_at)]
    .filter((date): date is Date => date !== null)
    .sort((a, b) => b.getTime() - a.getTime())[0];
  const lastSynced = !status
    ? "Backend unavailable"
    : !canSync
      ? "Set up Canvas or Ed to sync"
      : synced
        ? `Synced ${formatRelative(synced, now)}`
        : "Not synced yet";

  return (
    <DoneProvider>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            <NextLink href="/" className="brand-link">
              <AppMark />
              <span>Academic Assistant</span>
            </NextLink>
            {demo ? <span className="demo-pill">Demo</span> : null}
          </div>
          <nav aria-label="Main" className="side-nav">
            <NavLink href="/" className="nav-item">
              <TodayIcon />
              <span className="nav-label">Today</span>
            </NavLink>
            <NavLink href="/notifications" className="nav-item">
              <BellIcon />
              <span className="nav-label">Notifications</span>
              <Badge count={unread} label="unread" />
            </NavLink>
            <SidebarCourses courses={courses} edCourses={edOnly} />
          </nav>
          <div className="side-foot">
            <SyncControl disabled={!canSync} lastSynced={lastSynced} />
          </div>
        </aside>

        <header className="topbar">
          <NextLink href="/" className="brand-link">
            <AppMark size={24} />
            <span>Academic Assistant</span>
          </NextLink>
          {demo ? <span className="demo-pill">Demo</span> : null}
          <SyncControl disabled={!canSync} variant="icon" />
        </header>

        <main id="main" className="main" tabIndex={-1}>
          {children}
        </main>

        <nav aria-label="Main" className="tabbar">
          <NavLink href="/" className="tab">
            <TodayIcon size={22} />
            <span>Today</span>
          </NavLink>
          <NavLink href="/courses" className="tab" section>
            <CoursesIcon size={22} />
            <span>Courses</span>
          </NavLink>
          <NavLink href="/notifications" className="tab">
            <span className="tab-icon">
              <BellIcon size={22} />
              {unread ? <span className="tab-dot" aria-hidden="true" /> : null}
            </span>
            <span>
              Notifications
              {unread ? <span className="visually-hidden">, {unread} unread</span> : null}
            </span>
          </NavLink>
        </nav>
      </div>
    </DoneProvider>
  );
}
