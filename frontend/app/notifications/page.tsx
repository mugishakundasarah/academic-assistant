import type { Metadata } from "next";
import NextLink from "next/link";

import { getCourses, getNotifications, type Notification } from "../_lib/api";
import { courseLabel } from "../_lib/course";
import { dayDiff, parseDate } from "../_lib/format";
import { markAllRead } from "../actions";
import { NotificationRow } from "../components/NotificationRow";
import { BackendDown, EmptyState } from "../components/ui";

export const metadata: Metadata = { title: "Notifications" };

const GROUPS = ["Today", "Yesterday", "Earlier"] as const;

function group(notification: Notification, now: Date): (typeof GROUPS)[number] {
  const created = parseDate(notification.created_at);
  const diff = created ? dayDiff(created, now) : -2;
  return diff >= 0 ? "Today" : diff === -1 ? "Yesterday" : "Earlier";
}

export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { filter } = await searchParams;
  const unreadOnly = filter === "unread";
  const now = new Date();
  const [result, coursesResult] = await Promise.all([
    getNotifications({ unreadOnly, limit: 50 }),
    getCourses(),
  ]);
  const unreadCount = result.ok ? result.data.unread_count : 0;
  const notifications = result.ok ? result.data.notifications : [];
  const labels = new Map<number, string>(
    (coursesResult.ok ? coursesResult.data.courses : []).map((course) => [course.id, courseLabel(course)]),
  );
  const grouped = GROUPS.map((name) => ({
    name,
    items: notifications.filter((notification) => group(notification, now) === name),
  })).filter((entry) => entry.items.length);

  return (
    <div className="page">
      <header className="page-head page-head-row">
        <h1>Notifications</h1>
        {unreadCount ? (
          <form action={markAllRead}>
            <button type="submit" className="button button-quiet">
              Mark all read
            </button>
          </form>
        ) : null}
      </header>

      <nav aria-label="Filter notifications" className="segmented">
        <NextLink href="/notifications" aria-current={!unreadOnly ? "page" : undefined}>
          All
        </NextLink>
        <NextLink href="/notifications?filter=unread" aria-current={unreadOnly ? "page" : undefined}>
          Unread{unreadCount ? <span className="segmented-count">{unreadCount}</span> : null}
        </NextLink>
      </nav>

      {!result.ok ? (
        <BackendDown message={result.message} />
      ) : grouped.length ? (
        grouped.map(({ name, items }) => (
          <section key={name} aria-labelledby={`group-${name}`} className="section">
            <div className="section-head">
              <h2 id={`group-${name}`}>{name}</h2>
            </div>
            <ul className="notes">
              {items.map((notification) => (
                <NotificationRow key={notification.id} notification={notification} now={now} courseLabels={labels} />
              ))}
            </ul>
          </section>
        ))
      ) : (
        <EmptyState title={unreadOnly ? "You’re all caught up" : "No notifications yet"}>
          <p>
            {unreadOnly ? (
              <NextLink href="/notifications">Show all notifications</NextLink>
            ) : (
              "New announcements, new assignments and due date changes appear here after a sync."
            )}
          </p>
        </EmptyState>
      )}
    </div>
  );
}
