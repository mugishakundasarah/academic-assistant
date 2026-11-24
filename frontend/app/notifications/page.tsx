import NextLink from "next/link";

import { getNotifications, type Notification } from "../_lib/api";
import { formatDateTime, formatRelative, parseDate } from "../_lib/format";
import { markAllRead, markRead } from "../actions";
import { BackendDown, DateTime, EmptyState, ExternalLink, SiteHeader } from "../components/ui";

export const dynamic = "force-dynamic";

const TYPE_LABELS: Record<Notification["type"], string> = {
  new_announcement: "New announcement",
  new_assignment: "New assignment",
  due_date_changed: "Due date changed",
  assignment_updated: "Assignment updated",
};

function NotificationRow({ notification, now }: { notification: Notification; now: Date }) {
  const unread = notification.read_at === null;
  const created = parseDate(notification.created_at);
  const item = notification.item;
  return (
    <li className={`notification${unread ? " is-unread" : ""}`}>
      <div className="notification-body">
        <p className="notification-meta">
          {unread ? <span className="unread-dot" aria-hidden="true" /> : null}
          <span className="visually-hidden">{unread ? "Unread: " : "Read: "}</span>
          <span className="notification-type">{TYPE_LABELS[notification.type] ?? "Update"}</span>
          {created ? (
            <time dateTime={created.toISOString()} title={formatDateTime(created, now)}>
              {formatRelative(created, now)}
            </time>
          ) : null}
        </p>
        <p className="notification-message">{notification.message}</p>
        {item.kind === "assignment" && notification.due_at ? (
          <p className="notification-date">
            <DateTime value={notification.due_at} prefix="Due" now={now} />
          </p>
        ) : item.kind === "announcement" && item.posted_at ? (
          <p className="notification-date">
            <DateTime value={item.posted_at} prefix="Posted" now={now} />
          </p>
        ) : null}
        <p className="notification-links">
          <NextLink href={`/courses/${item.course_id}#item-${item.id}`}>
            View in {item.course_name}
          </NextLink>
          <ExternalLink href={item.html_url}>Open in Canvas</ExternalLink>
        </p>
      </div>
      {unread ? (
        <form action={markRead} className="notification-action">
          <input type="hidden" name="id" value={notification.id} />
          <button type="submit" className="button button-small">
            Mark read
            <span className="visually-hidden">: {notification.message}</span>
          </button>
        </form>
      ) : null}
    </li>
  );
}

export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { filter } = await searchParams;
  const unreadOnly = filter === "unread";
  const now = new Date();
  const result = await getNotifications({ unreadOnly, limit: 50 });
  const unreadCount = result.ok ? result.data.unread_count : null;
  const notifications = result.ok ? result.data.notifications : [];

  return (
    <>
      <SiteHeader unreadCount={unreadCount} healthy={result.ok || result.status !== null} />
      <main className="page">
        <div className="page-title-row">
          <h1>Notifications</h1>
          {unreadCount ? (
            <form action={markAllRead}>
              <button type="submit" className="button">
                Mark all read
              </button>
            </form>
          ) : null}
        </div>

        <nav aria-label="Filter notifications" className="filter-toggle">
          <NextLink
            href="/notifications"
            aria-current={!unreadOnly ? "page" : undefined}
          >
            All
          </NextLink>
          <NextLink
            href="/notifications?filter=unread"
            aria-current={unreadOnly ? "page" : undefined}
          >
            Unread{unreadCount ? ` (${unreadCount})` : ""}
          </NextLink>
        </nav>

        {!result.ok ? (
          <BackendDown message={result.message} />
        ) : notifications.length ? (
          <ul className="notification-list">
            {notifications.map((notification) => (
              <NotificationRow key={notification.id} notification={notification} now={now} />
            ))}
          </ul>
        ) : (
          <EmptyState title={unreadOnly ? "No unread notifications" : "No notifications yet"}>
            <p>
              {unreadOnly ? (
                <NextLink href="/notifications">Show all notifications</NextLink>
              ) : (
                <>
                  New announcements, new assignments and due date changes appear here after
                  a <NextLink href="/">sync</NextLink>.
                </>
              )}
            </p>
          </EmptyState>
        )}
      </main>
    </>
  );
}
