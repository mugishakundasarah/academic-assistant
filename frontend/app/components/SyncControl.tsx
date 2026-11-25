"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import type { CombinedSyncSummary, SyncError } from "../_lib/api";
import { syncNow, type SyncState } from "../actions";
import { SyncIcon } from "./icons";

function count(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "3 courses · 2 new items · 1 Ed announcement" */
function summaryLine(summary: CombinedSyncSummary) {
  const parts: string[] = [];
  if (summary.canvas) {
    parts.push(count(summary.canvas.courses, "course"), count(summary.canvas.items_added, "new item"));
  }
  if (summary.ed) parts.push(count(summary.ed.notifications_created, "Ed announcement"));
  return parts.length ? `Synced: ${parts.join(" · ")}` : "Synced.";
}

function sourceErrors(summary: CombinedSyncSummary) {
  const errors: { source: string; error: SyncError }[] = [];
  for (const error of summary.canvas?.errors ?? []) errors.push({ source: "Canvas", error });
  for (const error of summary.ed?.errors ?? []) errors.push({ source: "Ed", error });
  return errors;
}

function SyncButton({ disabled, variant }: { disabled: boolean; variant: Variant }) {
  const { pending } = useFormStatus();
  const label = pending ? "Syncing…" : "Sync now";
  if (variant === "icon") {
    return (
      <button
        type="submit"
        className={`icon-button sync-icon-button${pending ? " is-syncing" : ""}`}
        disabled={disabled || pending}
        title={label}
      >
        <SyncIcon />
        <span className="visually-hidden">{label}</span>
      </button>
    );
  }
  return (
    <button
      type="submit"
      className={`button ${variant === "primary" ? "button-primary" : "button-quiet"} sync-button${pending ? " is-syncing" : ""}`}
      disabled={disabled || pending}
    >
      <SyncIcon size={18} />
      {label}
    </button>
  );
}

type Variant = "sidebar" | "icon" | "primary";

/**
 * The sync control. "sidebar" sits at the foot of the desktop sidebar,
 * "icon" in the mobile top bar, "primary" in the first-run empty state.
 * ``lastSynced`` is server-formatted ("Synced 5 minutes ago").
 */
export function SyncControl({
  disabled,
  lastSynced,
  variant = "sidebar",
}: {
  disabled: boolean;
  lastSynced?: string;
  variant?: Variant;
}) {
  const [state, formAction] = useActionState<SyncState>(syncNow, { status: "idle" });
  const errors = state.status === "done" ? sourceErrors(state.summary) : [];

  return (
    <div className={`sync sync-${variant}`}>
      <form action={formAction}>
        <SyncButton disabled={disabled} variant={variant} />
      </form>
      {variant === "sidebar" && lastSynced ? <p className="sync-when">{lastSynced}</p> : null}
      <div role="status" aria-live="polite" className="sync-status">
        {state.status === "done" && variant !== "icon" ? (
          <p className={errors.length ? "sync-message is-warn" : "sync-message"}>
            {summaryLine(state.summary)}
          </p>
        ) : null}
        {errors.length ? (
          <ul className="sync-errors">
            {errors.map(({ source, error }, index) => (
              <li key={index}>
                {source}
                {error.course_name ? ` · ${error.course_name}` : ""}: {error.message}
              </li>
            ))}
          </ul>
        ) : null}
        {state.status === "error" ? <p className="sync-message is-error">Sync failed: {state.message}</p> : null}
      </div>
    </div>
  );
}
