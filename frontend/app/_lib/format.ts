// Date and URL helpers. All formatting runs on the server, so dates use the
// server's local time zone (the app is meant to run on the student's machine).
// The backend's "today" uses the same zone (see serverTimeZone).

const weekdayFormat = new Intl.DateTimeFormat("en-US", { weekday: "short" });
const monthDayFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const monthDayYearFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});
const longDayFormat = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
});
const fullFormat = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  month: "long",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});
const utcMonthDayFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const relativeFormat = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });

/** The Next server's IANA time zone; passed to the backend so both agree on "today". */
export function serverTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** Whole local calendar days from now's day to date's day (negative in the past). */
export function dayDiff(date: Date, now: Date): number {
  return Math.round((startOfDay(date).getTime() - startOfDay(now).getTime()) / 86_400_000);
}

/** "Today", "Tomorrow", "Yesterday", "Tue" (within the next 6 days), else "Dec 4". */
export function dayLabel(date: Date, now: Date): string {
  const diff = dayDiff(date, now);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  if (diff > 1 && diff < 7) return weekdayFormat.format(date);
  return date.getFullYear() === now.getFullYear()
    ? monthDayFormat.format(date)
    : monthDayYearFormat.format(date);
}

/** dayLabel for use mid-sentence: "today", "tomorrow", "Tue", "Dec 4". */
export function dayPhrase(date: Date, now: Date): string {
  const day = dayLabel(date, now);
  return ["Today", "Tomorrow", "Yesterday"].includes(day) ? day.toLowerCase() : day;
}

/** "5 PM", "11:59 PM". */
export function timeLabel(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const suffix = hours < 12 ? "AM" : "PM";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return minutes === 0
    ? `${hour12} ${suffix}`
    : `${hour12}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

/** "Thu 5 PM", "today 11:59 PM", "Dec 4, 9 AM". */
export function dayTimeLabel(date: Date, now: Date): string {
  const day = dayPhrase(date, now);
  // A calendar date takes a comma before the time: "Dec 7, 5 PM".
  return /\d/.test(day) ? `${day}, ${timeLabel(date)}` : `${day} ${timeLabel(date)}`;
}

/** "Wed, Nov 25". */
export function longDay(date: Date): string {
  return longDayFormat.format(date);
}

/** "Wednesday, November 25, 2026 at 5:00 PM PST", for title attributes. */
export function fullDateTime(date: Date): string {
  return fullFormat.format(date);
}

/** "Nov 30" for a UTC week start (Monday 00:00 UTC). */
export function weekLabel(date: Date): string {
  return utcMonthDayFormat.format(date);
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

/** Compact past time: "now", "12m", "3h", "Yesterday", "Mon", "Nov 3". */
export function shortAgo(date: Date, now: Date): string {
  const diff = now.getTime() - date.getTime();
  if (diff < MINUTE) return "now";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m`;
  if (diff < DAY && dayDiff(date, now) === 0) return `${Math.floor(diff / HOUR)}h`;
  const days = dayDiff(date, now);
  if (days === -1) return "Yesterday";
  if (days > -7) return weekdayFormat.format(date);
  return monthDayFormat.format(date);
}

/** "Good morning" / "Good afternoon" / "Good evening" for the server's local hour. */
export function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 5) return "Good evening";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
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

/** "100 pts", "12.5 pts", "1 pt". */
export function points(value: number): string {
  const text = Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
  return `${text} ${value === 1 ? "pt" : "pts"}`;
}
