"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

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
        {state.status === "done" ? (
          <div
            className={
              state.summary.errors.length ? "notice notice-warn" : "notice notice-ok"
            }
          >
            <p>
              Synced {count(state.summary.courses, "course")}:{" "}
              {count(state.summary.items_added, "new item")},{" "}
              {count(state.summary.items_updated, "updated item")},{" "}
              {count(state.summary.notifications_created, "notification")}.
            </p>
            {state.summary.errors.length ? (
              <>
                <p>Some courses could not be synced:</p>
                <ul>
                  {state.summary.errors.map((error, index) => (
                    <li key={index}>
                      {error.course_name ? <strong>{error.course_name}: </strong> : null}
                      {error.message}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}
        {state.status === "error" ? (
          <div className="notice notice-error">
            <p>Sync failed: {state.message}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
