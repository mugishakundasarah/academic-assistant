import NextLink from "next/link";
import type { ReactNode } from "react";

import type { Item, Link } from "../_lib/api";
import {
  formatDateTime,
  formatRelative,
  parseDate,
  safeHref,
  toParagraphs,
} from "../_lib/format";

/** Link to Canvas (or another external site). Renders nothing for non-http(s) URLs. */
export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string | null | undefined;
  children: ReactNode;
  className?: string;
}) {
  const safe = safeHref(href);
  if (!safe) return null;
  return (
    <a href={safe} className={className} target="_blank" rel="noopener noreferrer">
      {children}
      <span className="visually-hidden"> (opens in a new tab)</span>
      <span aria-hidden="true" className="external-mark">
        ↗
      </span>
    </a>
  );
}

function FileIcon() {
  return (
    <svg className="link-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M4 1.5h5l3.5 3.5v9.5h-8.5z M9 1.5v3.5h3.5 M8.25 7v5 M6 10l2.25 2.25L10.5 10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function LinkIcon() {
  return (
    <svg className="link-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M6.5 9.5l3-3 M7 4.5l1.2-1.2a2.5 2.5 0 013.5 3.5L10.5 8 M9 11.5l-1.2 1.2a2.5 2.5 0 01-3.5-3.5L5.5 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function DateTime({
  value,
  prefix,
  relative = true,
  now,
}: {
  value: string | null | undefined;
  prefix?: string;
  relative?: boolean;
  now: Date;
}) {
  const date = parseDate(value);
  if (!date) return null;
  return (
    <time dateTime={date.toISOString()} title={date.toString()}>
      {prefix ? `${prefix} ` : ""}
      {formatDateTime(date, now)}
      {relative ? ` · ${formatRelative(date, now)}` : ""}
    </time>
  );
}

export function Paragraphs({ text }: { text: string }) {
  const paragraphs = toParagraphs(text);
  if (paragraphs.length === 0) return null;
  return (
    <div className="prose">
      {paragraphs.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </div>
  );
}

/** Assignment instructions: shown inline when short, collapsed when long. */
export function ItemText({ text, collapseAfter }: { text: string; collapseAfter: number }) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (trimmed.length <= collapseAfter) return <Paragraphs text={trimmed} />;
  return (
    <details className="item-text-details">
      <summary>Instructions</summary>
      <Paragraphs text={trimmed} />
    </details>
  );
}

export function LinkList({ links }: { links: Link[] }) {
  const safeLinks = links.filter((link) => safeHref(link.url));
  if (safeLinks.length === 0) return null;
  return (
    <ul className="link-list" aria-label="Files and links">
      {safeLinks.map((link) => (
        <li key={link.url}>
          <ExternalLink
            href={link.url}
            className={link.kind === "file" ? "file-link" : "plain-link"}
          >
            {link.kind === "file" ? <FileIcon /> : <LinkIcon />}
            <span className="visually-hidden">
              {link.kind === "file" ? "File: " : "Link: "}
            </span>
            {link.title || link.url}
          </ExternalLink>
        </li>
      ))}
    </ul>
  );
}

const ACTION_LABELS: Record<string, string> = {
  read: "Read",
  submit: "Submit",
  quiz: "Quiz",
  discussion: "Discussion",
};

export function TypeBadge({ item }: { item: Item }) {
  if (item.kind === "announcement") {
    return <span className="badge badge-announcement">Announcement</span>;
  }
  const action = item.action ?? "submit";
  return (
    <span className={`badge badge-${action}`}>
      {ACTION_LABELS[action] ?? "Task"}
    </span>
  );
}

export function ItemCard({
  item,
  now,
  featured = false,
  showCourse = true,
  headingLevel = 3,
}: {
  item: Item;
  now: Date;
  featured?: boolean;
  showCourse?: boolean;
  headingLevel?: 2 | 3 | 4;
}) {
  const Heading = `h${headingLevel}` as "h2" | "h3" | "h4";
  const due = parseDate(item.due_at);
  const overdue = !item.completed && due !== null && due < now;
  return (
    <article
      className={`item-card${featured ? " item-featured" : ""}${item.completed ? " item-done" : ""}`}
      id={`item-${item.id}`}
    >
      <div className="item-meta">
        <TypeBadge item={item} />
        {item.platform === "gradescope" ? (
          <span className="badge">Gradescope</span>
        ) : null}
        {item.missing ? <span className="badge badge-missing">Missing</span> : null}
        {item.completed ? <span className="badge badge-done">Done</span> : null}
        {showCourse ? (
          <NextLink href={`/courses/${item.course_id}`} className="course-name">
            {item.course_name}
          </NextLink>
        ) : null}
      </div>
      <Heading className="item-title">{item.title}</Heading>
      <p className={`item-due${overdue ? " is-overdue" : ""}`}>
        {due ? (
          <DateTime value={item.due_at} prefix="Due" now={now} />
        ) : item.kind === "assignment" ? (
          "No due date"
        ) : null}
        {item.points_possible !== null && item.points_possible !== undefined ? (
          <span className="points"> · {item.points_possible} pts</span>
        ) : null}
      </p>
      <ItemText text={item.text} collapseAfter={featured ? 800 : 300} />
      <LinkList links={item.links} />
      <ExternalLink href={item.html_url} className="canvas-link">
        Open in Canvas
      </ExternalLink>
    </article>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <p className="empty-title">{title}</p>
      {children}
    </div>
  );
}

export function BackendDown({ message }: { message: string }) {
  return (
    <div className="notice notice-error" role="alert">
      <p>
        <strong>Cannot reach the backend.</strong> {message} Start FastAPI as
        described in the README, then reload this page.
      </p>
    </div>
  );
}

export function SiteHeader({
  unreadCount,
  healthy,
}: {
  unreadCount: number | null;
  healthy: boolean | null;
}) {
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <NextLink href="/" className="brand">
          Academic Assistant
        </NextLink>
        <nav aria-label="Main">
          <ul>
            <li>
              <NextLink href="/">Dashboard</NextLink>
            </li>
            <li>
              <NextLink href="/notifications" className="nav-notifications">
                Notifications
                {unreadCount ? (
                  <span className="count-pill">
                    {unreadCount}
                    <span className="visually-hidden"> unread</span>
                  </span>
                ) : null}
              </NextLink>
            </li>
          </ul>
        </nav>
        {healthy !== null ? (
          <span className="health" data-connected={healthy}>
            {healthy ? "Backend connected" : "Backend unavailable"}
          </span>
        ) : null}
      </div>
    </header>
  );
}
