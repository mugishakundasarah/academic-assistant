"use server";

import { revalidatePath } from "next/cache";

import {
  markAllNotificationsRead,
  markItemDone,
  markNotificationRead,
  runSync,
  unmarkItemDone,
  type CombinedSyncSummary,
} from "./_lib/api";

export type SyncState =
  | { status: "idle" }
  | { status: "done"; summary: CombinedSyncSummary }
  | { status: "error"; message: string };

export async function syncNow(_previous: SyncState): Promise<SyncState> {
  const result = await runSync();
  // Refresh every page so new items and notification counts appear.
  revalidatePath("/", "layout");
  if (result.ok) return { status: "done", summary: result.data };

  let message = result.message;
  if (result.status === 409) message = "A sync is already running. Try again shortly.";
  return { status: "error", message };
}

function parseId(value: FormDataEntryValue | null): number | null {
  if (typeof value !== "string" || !/^\d{1,15}$/.test(value)) return null;
  const id = Number(value);
  return id > 0 ? id : null;
}

export async function markRead(formData: FormData): Promise<void> {
  const id = parseId(formData.get("id"));
  if (id === null) return;
  await markNotificationRead(id);
  revalidatePath("/", "layout");
}

export async function markAllRead(): Promise<void> {
  await markAllNotificationsRead();
  revalidatePath("/", "layout");
}

export type DoneResult = { ok: true; done: boolean } | { ok: false; message: string };

/**
 * Set or clear an item's local done mark. Arguments come from the browser, so
 * both are validated here. This does not revalidate: the row keeps showing
 * its Undo until the client calls refreshViews, so the item does not vanish
 * under the cursor.
 */
export async function setItemDone(id: unknown, done: unknown): Promise<DoneResult> {
  if (typeof id !== "number" || !Number.isSafeInteger(id) || id < 1) {
    return { ok: false, message: "Unknown item." };
  }
  if (typeof done !== "boolean") return { ok: false, message: "Invalid request." };
  const result = done ? await markItemDone(id) : await unmarkItemDone(id);
  if (!result.ok) {
    return {
      ok: false,
      message: result.status === 404 ? "This item no longer exists. Try syncing." : result.message,
    };
  }
  return { ok: true, done: Boolean(result.data.done) };
}

/** Re-render every page after done marks settle, so lists and counts update. */
export async function refreshViews(): Promise<void> {
  revalidatePath("/", "layout");
}
