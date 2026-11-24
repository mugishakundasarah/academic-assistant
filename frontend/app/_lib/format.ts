// Date and URL helpers. All formatting runs on the server, so dates use the
// server's local time zone (the app is meant to run on the student's machine).

const dateTimeFormat = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const dateTimeWithYearFormat = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const shortDateFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

const relativeFormat = new Intl.RelativeTimeFormat("en-US", {
  numeric: "auto",
});

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "Tue, Dec 2, 11:59 PM" (year added when it differs from now). */
export function formatDateTime(date: Date, now = new Date()): string {
  return date.getFullYear() === now.getFullYear()
    ? dateTimeFormat.format(date)
    : dateTimeWithYearFormat.format(date);
}

export function formatShortDate(date: Date): string {
  return shortDateFormat.format(date);
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "in 3 days", "5 hours ago", "in 20 minutes", "just now". */
export function formatRelative(date: Date, now = new Date()): string {
  const diff = date.getTime() - now.getTime();
  const abs = Math.abs(diff);
  if (abs < MINUTE) return "just now";
  if (abs < HOUR) return relativeFormat.format(Math.round(diff / MINUTE), "minute");
  if (abs < DAY) return relativeFormat.format(Math.round(diff / HOUR), "hour");
  return relativeFormat.format(Math.round(diff / DAY), "day");
}

/** Returns the URL only when it is an absolute http(s) URL. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url || !/^https?:\/\//i.test(url)) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

/** Split plain text into paragraphs on blank lines. */
export function toParagraphs(text: string): string[] {
  return text
    .split(/\r?\n[ \t]*\r?\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

export function plural(count: number, singular: string, pluralForm?: string) {
  return `${count} ${count === 1 ? singular : (pluralForm ?? `${singular}s`)}`;
}
