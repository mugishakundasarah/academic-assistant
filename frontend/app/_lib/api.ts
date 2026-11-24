// Server-side client for the FastAPI backend. The browser never calls the
// backend directly: pages and Server Actions use these helpers, which read
// BACKEND_URL from the Next.js server environment.

export type ItemKind = "assignment" | "announcement";
export type ItemAction = "read" | "submit" | "quiz" | "discussion";
export type NotificationType =
  | "new_announcement"
  | "new_assignment"
  | "due_date_changed"
  | "assignment_updated";

export type Course = {
  id: number;
  name: string;
  course_code: string | null;
  synced_at: string | null;
  open_count: number;
  next_due_at: string | null;
  unread_count: number;
};

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
};

export type Notification = {
  id: number;
  type: NotificationType;
  message: string;
  created_at: string;
  read_at: string | null;
  item: Item;
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
  init: { method?: "GET" | "POST"; timeoutMs?: number } = {},
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

export async function getHealth(): Promise<boolean> {
  const result = await request<{ status?: unknown }>("/health", {
    timeoutMs: 2000,
  });
  return result.ok && result.data.status === "ok";
}

export function getCanvasStatus() {
  return request<CanvasStatus>("/api/canvas/status");
}

export function runSync() {
  return request<SyncSummary>("/api/canvas/sync", {
    method: "POST",
    timeoutMs: SYNC_TIMEOUT_MS,
  });
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
