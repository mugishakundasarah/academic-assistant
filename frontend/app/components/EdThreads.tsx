import type { EdThread } from "../_lib/api";
import { DateTime, EmptyState, ExternalLink, ItemText } from "./ui";

export const ED_EMPTY_TEXT = "No staff announcements on Ed in the last 30 days.";

function EdThreadCard({ thread, now }: { thread: EdThread; now: Date }) {
  return (
    <article className="announcement" id={`ed-thread-${thread.id}`}>
      <div className="item-meta">
        {thread.is_pinned ? (
          <span className="badge badge-pinned">Pinned</span>
        ) : (
          <span className="badge badge-announcement">Announcement</span>
        )}
        {thread.category ? <span className="muted">{thread.category}</span> : null}
      </div>
      <h3 className="item-title">{thread.title}</h3>
      <p className="muted small">
        <DateTime value={thread.created_at} prefix="Posted" now={now} />
      </p>
      <ItemText text={thread.text} collapseAfter={400} summary="Show message" />
      <ExternalLink href={thread.url} className="canvas-link">
        Open in Ed
      </ExternalLink>
    </article>
  );
}

/** Pinned and recent announcement threads from one Ed course, in the order the backend returns. */
export function EdThreadList({ threads, now }: { threads: EdThread[]; now: Date }) {
  if (threads.length === 0) return <EmptyState title={ED_EMPTY_TEXT} />;
  return (
    <ul className="item-list">
      {threads.map((thread) => (
        <li key={thread.id}>
          <EdThreadCard thread={thread} now={now} />
        </li>
      ))}
    </ul>
  );
}
