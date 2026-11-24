"use server";

import { revalidatePath } from "next/cache";

import {
  markAllNotificationsRead,
  markNotificationRead,
  runSync,
  type SyncSummary,
} from "./_lib/api";

export type SyncState =
  | { status: "idle" }
  | { status: "done"; summary: SyncSummary }
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
