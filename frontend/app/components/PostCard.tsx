import type { ReactNode } from "react";

import type { EdThread, Item } from "../_lib/api";
import { fullDateTime, longDay, parseDate } from "../_lib/format";
import { PinIcon } from "./icons";
import { CollapsibleText, EmptyState, ExternalLink, LinkChips } from "./ui";

function Posted({ value }: { value: string | null }) {
  const date = parseDate(value);
  if (!date) return null;
  return (
    <time dateTime={date.toISOString()} title={fullDateTime(date)}>
      {longDay(date)}
    </time>
  );
}

/** A Canvas announcement or an Ed thread as a calm reading card. */
function Post({
  id,
  kicker,
  pinned = false,
  title,
  meta,
  text,
  children,
}: {
  id: string;
  kicker: string;
  pinned?: boolean;
  title: string;
  meta: ReactNode;
  text: string;
  children?: ReactNode;
}) {
  return (
    <article className="post" id={id}>
      <p className="post-kicker">
        {pinned ? <PinIcon size={14} /> : null}
        <span>{kicker}</span>
        <span className="post-meta">{meta}</span>
      </p>
      <h3 className="post-title">{title}</h3>
      {text.trim() ? (
        <CollapsibleText text={text} label="Read more" collapseAfter={240} />
      ) : (
        <p className="post-empty">No message text.</p>
      )}
      {children}
    </article>
  );
}

export function AnnouncementCard({ item }: { item: Item }) {
  return (
    <Post
      id={`item-${item.id}`}
      kicker="Announcement"
      title={item.title}
      text={item.text}
      meta={
        <>
          {item.author ? <span>{item.author}</span> : null}
          <Posted value={item.posted_at} />
        </>
      }
    >
      <LinkChips links={item.links} />
      <div className="post-actions">
        <ExternalLink href={item.html_url} className="text-button">
          Open in Canvas
        </ExternalLink>
      </div>
    </Post>
  );
}

export function EdThreadCard({ thread }: { thread: EdThread }) {
  return (
    <Post
      id={`ed-thread-${thread.id}`}
      kicker={thread.is_pinned ? "Pinned" : "Announcement"}
      pinned={thread.is_pinned}
      title={thread.title}
      text={thread.text}
      meta={
        <>
          {thread.category ? <span>{thread.category}</span> : null}
          <Posted value={thread.created_at} />
        </>
      }
    >
      <div className="post-actions">
        <ExternalLink href={thread.url} className="text-button">
          Open in Ed
        </ExternalLink>
      </div>
    </Post>
  );
}

export const ED_EMPTY_TEXT = "No staff announcements on Ed in the last 30 days.";

/** Pinned and recent announcement threads from one Ed course, in the order the backend returns. */
export function EdThreadList({ threads }: { threads: EdThread[] }) {
  if (threads.length === 0) return <EmptyState title={ED_EMPTY_TEXT} />;
  return (
    <ul className="posts">
      {threads.map((thread) => (
        <li key={thread.id}>
          <EdThreadCard thread={thread} />
        </li>
      ))}
    </ul>
  );
}
