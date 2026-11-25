import type { ReactNode } from "react";

import type { Item, Link } from "../_lib/api";
import { courseHue } from "../_lib/course";
import { formatRelative, fullDateTime, parseDate, safeHref, toParagraphs } from "../_lib/format";
import { ExternalIcon, FileIcon, LinkIcon } from "./icons";

/**
 * Link to Canvas, Ed or a file. Renders nothing for non-http(s) URLs, and
 * always opens in a new tab without an opener or referrer.
 */
export function ExternalLink({
  href,
  children,
  className,
  icon = true,
}: {
  href: string | null | undefined;
  children: ReactNode;
  className?: string;
  icon?: boolean;
}) {
  const safe = safeHref(href);
  if (!safe) return null;
  return (
    <a href={safe} className={className} target="_blank" rel="noopener noreferrer">
      {children}
      <span className="visually-hidden"> (opens in a new tab)</span>
      {icon ? <ExternalIcon size={14} className="external-icon" /> : null}
    </a>
  );
}

/** "3 hours ago" with the full date as a tooltip. */
export function TimeAgo({ value, now }: { value: string | null | undefined; now: Date }) {
  const date = parseDate(value);
  if (!date) return null;
  return (
    <time dateTime={date.toISOString()} title={fullDateTime(date)}>
      {formatRelative(date, now)}
    </time>
  );
}

export function Paragraphs({ text, className = "prose" }: { text: string; className?: string }) {
  const paragraphs = toParagraphs(text);
  if (paragraphs.length === 0) return null;
  return (
    <div className={className}>
      {paragraphs.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </div>
  );
}

/** Long text collapsed behind a two-line preview; short text shown as is. */
export function CollapsibleText({
  text,
  label,
  collapseAfter = 280,
}: {
  text: string;
  label: string;
  collapseAfter?: number;
}) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (trimmed.length <= collapseAfter) return <Paragraphs text={trimmed} />;
  return (
    <details className="more">
      <summary>
        <span className="more-preview">{toParagraphs(trimmed)[0]}</span>
        <span className="more-toggle">{label}</span>
      </summary>
      <Paragraphs text={trimmed} />
    </details>
  );
}

/** Files and links as compact chips. */
export function LinkChips({ links }: { links: Link[] }) {
  const safeLinks = links.filter((link) => safeHref(link.url));
  if (safeLinks.length === 0) return null;
  return (
    <ul className="chips" aria-label="Files and links">
      {safeLinks.map((link) => (
        <li key={link.url}>
          <ExternalLink href={link.url} className="chip-link" icon={false}>
            {link.kind === "file" ? <FileIcon size={15} /> : <LinkIcon size={15} />}
            <span className="visually-hidden">{link.kind === "file" ? "File: " : "Link: "}</span>
            <span className="chip-text">{link.title || link.url}</span>
          </ExternalLink>
        </li>
      ))}
    </ul>
  );
}

/** A course's colour dot; the colour comes from the course id. */
export function CourseDot({ id, source = "canvas" }: { id: number; source?: "canvas" | "ed" }) {
  return <span className="course-dot" data-hue={courseHue(id, source)} aria-hidden="true" />;
}

const ACTION_LABELS: Record<string, string> = {
  read: "Read",
  submit: "Submit",
  quiz: "Quiz",
  discussion: "Discussion",
};

/** "Read", "Submit", "Quiz", "Discussion" or "Gradescope". */
export function TypeChip({ item }: { item: Item }) {
  if (item.kind === "announcement") return <span className="type-chip">Announcement</span>;
  if (item.platform === "gradescope") {
    return <span className="type-chip" data-type="gradescope">Gradescope</span>;
  }
  const action = item.action ?? "submit";
  return (
    <span className="type-chip" data-type={action}>
      {ACTION_LABELS[action] ?? "Task"}
    </span>
  );
}

export function EmptyState({
  title,
  children,
  icon,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      {icon ? <div className="empty-icon">{icon}</div> : null}
      <p className="empty-title">{title}</p>
      {children ? <div className="empty-body">{children}</div> : null}
    </div>
  );
}

export function BackendDown({ message }: { message: string }) {
  return (
    <div className="notice notice-error" role="alert">
      <p>
        <strong>Can’t reach the backend.</strong> {message} Start FastAPI as described in the README,
        then reload this page.
      </p>
    </div>
  );
}

export function SectionHeader({
  id,
  title,
  count,
  tone,
  action,
}: {
  id: string;
  title: string;
  count?: number;
  tone?: "danger";
  action?: ReactNode;
}) {
  return (
    <div className="section-head">
      <h2 id={id} className={tone === "danger" ? "is-danger" : undefined}>
        {title}
        {count !== undefined ? <span className="section-count">{count}</span> : null}
      </h2>
      {action}
    </div>
  );
}
