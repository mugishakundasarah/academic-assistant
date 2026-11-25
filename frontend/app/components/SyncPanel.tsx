"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import type { CombinedSyncSummary, SyncError } from "../_lib/api";
import { syncNow, type SyncState } from "../actions";

function SubmitButton({ disabled }: { disabled: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      className="button button-primary"
      disabled={disabled || pending}
      aria-disabled={disabled || pending}
    >
      {pending ? "Syncing…" : "Sync now"}
    </button>
  );
}

function count(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "Canvas: 3 courses, 2 new items · Ed: 2 courses, 1 new announcement" */
function summaryLine(summary: CombinedSyncSummary) {
  const parts: string[] = [];
  if (summary.canvas) {
    parts.push(
      `Canvas: ${count(summary.canvas.courses, "course")}, ${count(summary.canvas.items_added, "new item")}`,
    );
  }
  if (summary.ed) {
    parts.push(
      `Ed: ${count(summary.ed.courses, "course")}, ${count(summary.ed.notifications_created, "new announcement")}`,
    );
  }
  return parts.join(" · ");
}

function sourceErrors(summary: CombinedSyncSummary) {
  const errors: { source: string; error: SyncError }[] = [];
  for (const error of summary.canvas?.errors ?? []) errors.push({ source: "Canvas", error });
  for (const error of summary.ed?.errors ?? []) errors.push({ source: "Ed", error });
  return errors;
}

function SyncResult({ summary }: { summary: CombinedSyncSummary }) {
  const errors = sourceErrors(summary);
  return (
    <div className={errors.length ? "notice notice-warn" : "notice notice-ok"}>
      <p>{summaryLine(summary)}</p>
      {errors.length ? (
        <>
          <p>Some courses could not be synced:</p>
          <ul>
            {errors.map(({ source, error }, index) => (
              <li key={index}>
                <strong>
                  {source}
                  {error.course_name ? ` · ${error.course_name}` : ""}:{" "}
                </strong>
                {error.message}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

export function SyncPanel({
  disabled,
  disabledReason,
}: {
  disabled: boolean;
  disabledReason?: string;
}) {
  const [state, formAction] = useActionState<SyncState>(syncNow, {
    status: "idle",
  });

  return (
    <div className="sync-panel">
      <form action={formAction}>
        <SubmitButton disabled={disabled} />
      </form>
      {disabled && disabledReason ? (
        <p className="muted small">{disabledReason}</p>
      ) : null}
      <div aria-live="polite" role="status" className="sync-result">
        {state.status === "done" ? <SyncResult summary={state.summary} /> : null}
        {state.status === "error" ? (
          <div className="notice notice-error">
            <p>Sync failed: {state.message}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
