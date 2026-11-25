// Server-side client for the FastAPI backend. The browser never calls the
// backend directly: pages and Server Actions use these helpers, which read
// BACKEND_URL from the Next.js server environment.

export type ItemKind = "assignment" | "announcement";
export type ItemAction = "read" | "submit" | "quiz" | "discussion";
/** Where the work is done: "gradescope" for Canvas assignments that launch Gradescope. */
export type ItemPlatform = "canvas" | "gradescope";
export type NotificationType =
  | "new_announcement"
  | "new_assignment"
  | "due_date_changed"
  | "assignment_updated"
  | "ed_announcement";

export type Course = {
  id: number;
  name: string;
  course_code: string | null;
  synced_at: string | null;
  open_count: number;
  next_due_at: string | null;
  /** Includes unread Ed notifications of the matched Ed course. */
  unread_count: number;
  /** Matched Ed Discussion course (same normalized course code); optional for older backends. */
  ed_course_id?: number | null;
};

export type EdCourse = {
  id: number;
  code: string | null;
  name: string;
  /** Ed web page for the course. */
  url: string | null;
  synced_at: string | null;
  canvas_course_id: number | null;
};

/** A staff-style Ed thread: an announcement from the last 30 days or a pinned thread. */
export type EdThread = {
  id: number;
  ed_course_id: number;
  title: string;
  type: string | null;
  category: string | null;
  created_at: string | null;
  is_pinned: boolean;
  is_answered: boolean;
  /** Plain text; may be "". */
  text: string;
  url: string | null;
  first_seen_at: string;
};

export type EdCourseThreads = { ed_course: EdCourse | null; threads: EdThread[] };

export type Link = { title: string; url: string; kind: "file" | "link" };

export type Item = {
  id: number;
  kind: ItemKind;
  course_id: number;
  course_name: string;
  title: string;
  text: string;
  html_url: string | null;
  due_at: string | null;
  posted_at: string | null;
  action: ItemAction | null;
  completed: boolean;
  missing: boolean;
  points_possible: number | null;
  author: string | null;
  links: Link[];
  first_seen_at: string;
  updated_at: string;
  /** Optional so an older backend without the field still works; missing means "canvas". */
  platform?: ItemPlatform;
  /** Schema v6: the student's local done mark (Canvas is not changed). */
  done?: boolean;
  /** completed or done. */
  finished?: boolean;
  /** Planned start date (UTC Z), never earlier than now; null when undated or finished. */
  do_by?: string | null;
  /** Short explanation of do_by, e.g. "Big assignment (100 pts): start 4 days early". */
  do_by_reason?: string | null;
};

export type Week = { start: string; load: number; heavy: boolean; items: number[] };

/** GET /api/today: the morning digest. */
export type Today = {
  generated_at: string;
  do_today: Item[];
  due_today: Item[];
  overdue: Item[];
  /** Notifications from the last 24 hours, newest first, at most 10. */
  changes: Notification[];
  courses: { course: Course; next: Item[] }[];
  heavy_week: { start: string; load: number } | null;
};

export type Notification = {
  id: number;
  type: NotificationType;
  message: string;
  created_at: string;
  read_at: string | null;
  /**
   * Assignment due date as it was when the notification was created; null when
   * there was none. Optional so an older backend without the field still works.
   */
  due_at?: string | null;
  /** Null for Ed notifications. */
  item: Item | null;
  /** Set for Ed notifications; optional for older backends. */
  ed_thread?: EdThread | null;
  ed_course?: EdCourse | null;
};

export type EdStatus = {
  configured: boolean;
  demo: boolean;
  last_synced_at: string | null;
};

export type CanvasStatus = {
  configured: boolean;
  demo: boolean;
  syncing: boolean;
  last_synced_at: string | null;
};

export type SyncError = {
  course_id: number | null;
  course_name: string | null;
  message: string;
};

export type SyncSummary = {
  started_at: string;
  finished_at: string;
  courses: number;
  items_added: number;
  items_updated: number;
  notifications_created: number;
  errors: SyncError[];
};

export type EdSyncSummary = {
  courses: number;
  threads_added: number;
  threads_updated: number;
  notifications_created: number;
  errors: SyncError[];
};

/** POST /api/sync: each source is null when it is not configured. */
export type CombinedSyncSummary = {
  canvas: SyncSummary | null;
  ed: EdSyncSummary | null;
};

export type ApiResult<T> =
  | { ok: true; data: T }
  | {
      ok: false;
      /** HTTP status, or null when the backend could not be reached. */
      status: number | null;
      message: string;
    };

const READ_TIMEOUT_MS = 3000;
// A sync fetches every course from Canvas, so it gets a longer budget.
const SYNC_TIMEOUT_MS = 120_000;
const WRITE_TIMEOUT_MS = 5000;

function backendUrl(path: string): URL {
  const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  return new URL(path.replace(/^\//, ""), base.replace(/\/?$/, "/"));
}

function detailMessage(body: unknown): string | null {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return null;
}

async function request<T>(
  path: string,
  init: { method?: "GET" | "POST" | "DELETE"; timeoutMs?: number } = {},
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(backendUrl(path), {
      method: init.method ?? "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(init.timeoutMs ?? READ_TIMEOUT_MS),
    });
  } catch (error) {
    const timedOut =
      error instanceof Error &&
      (error.name === "TimeoutError" || error.name === "AbortError");
    return {
      ok: false,
      status: null,
      message: timedOut
        ? "The backend did not respond in time."
        : "The backend is unavailable.",
    };
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message:
        detailMessage(body) ??
        `The backend returned an error (HTTP ${response.status}).`,
    };
  }
  if (body === null || typeof body !== "object") {
    return {
      ok: false,
      status: response.status,
      message: "The backend returned an unexpected response.",
    };
  }
  return { ok: true, data: body as T };
}

export function getCanvasStatus() {
  return request<CanvasStatus>("/api/canvas/status");
}

export function getEdStatus() {
  return request<EdStatus>("/api/ed/status");
}

/** Syncs Canvas, then Ed, each only when configured. */
export function runSync() {
  return request<CombinedSyncSummary>("/api/sync", {
    method: "POST",
    timeoutMs: SYNC_TIMEOUT_MS,
  });
}

export function getEdCourses() {
  return request<{ courses: EdCourse[] }>("/api/ed/courses");
}

export function getEdCourse(edCourseId: number) {
  return request<EdCourseThreads>(`/api/ed/courses/${edCourseId}`);
}

export function getCourseEd(courseId: number) {
  return request<EdCourseThreads>(`/api/courses/${courseId}/ed`);
}

export function getCourses() {
  return request<{ courses: Course[] }>("/api/courses");
}

export function getCourse(courseId: number) {
  return request<Course>(`/api/courses/${courseId}`);
}

export function getCourseItems(courseId: number, kind: ItemKind) {
  return request<{ items: Item[] }>(
    `/api/courses/${courseId}/items?kind=${kind}`,
  );
}

export function getUpcoming(limit = 10) {
  return request<{ overdue: Item[]; upcoming: Item[] }>(
    `/api/upcoming?limit=${limit}`,
  );
}

export function getNotifications(options: {
  unreadOnly?: boolean;
  limit?: number;
} = {}) {
  const params = new URLSearchParams({
    unread_only: options.unreadOnly ? "true" : "false",
    limit: String(options.limit ?? 50),
  });
  return request<{ notifications: Notification[]; unread_count: number }>(
    `/api/notifications?${params}`,
  );
}

export function markNotificationRead(id: number) {
  return request<Notification>(`/api/notifications/${id}/read`, {
    method: "POST",
    timeoutMs: WRITE_TIMEOUT_MS,
  });
}

export function markAllNotificationsRead() {
  return request<{ updated: number }>("/api/notifications/read-all", {
    method: "POST",
    timeoutMs: WRITE_TIMEOUT_MS,
  });
}

/** "Today" is computed in the given IANA time zone (the Next server's own zone). */
export function getToday(timeZone: string) {
  return request<Today>(`/api/today?${new URLSearchParams({ tz: timeZone })}`);
}

export function getWeeks(count = 3) {
  return request<{ weeks: Week[] }>(`/api/weeks?count=${count}`);
}

export function markItemDone(id: number) {
  return request<Item>(`/api/items/${id}/done`, {
    method: "POST",
    timeoutMs: WRITE_TIMEOUT_MS,
  });
}

export function unmarkItemDone(id: number) {
  return request<Item>(`/api/items/${id}/done`, {
    method: "DELETE",
    timeoutMs: WRITE_TIMEOUT_MS,
  });
}

/** Finished = completed in Canvas or marked done locally (older backends: completed only). */
export function isFinished(item: Item): boolean {
  return item.finished ?? (item.completed || Boolean(item.done));
}
