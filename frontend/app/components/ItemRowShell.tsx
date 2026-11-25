"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { setItemDone } from "../actions";
import { useDoneHold } from "./DoneProvider";

/** How long "Done · Undo" stays in place before the row leaves its list. */
const UNDO_MS = 5000;
/** Matches --dur-slow in globals.css (the collapse transition). */
const LEAVE_MS = 320;

type Phase = "idle" | "undo" | "leaving" | "gone";

function CheckMark() {
  return (
    <svg className="check-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle className="check-ring" cx="12" cy="12" r="9.25" />
      <path className="check-tick" d="M7.75 12.25l2.75 2.75 5.75-6" pathLength={1} />
    </svg>
  );
}

/**
 * The interactive frame of an item row: the round checkbox, the done
 * styling and the in-place Undo. The row's content (title, dates, details)
 * is server-rendered and passed as children.
 *
 * Marking an open item done calls the Server Action at once, then shows
 * "Done · Undo" for a few seconds before the row collapses and the pages
 * are revalidated. Clearing a done mark (in a course's Done list)
 * revalidates straight away. Items completed in Canvas show a fixed check.
 */
export function ItemRowShell({
  itemId,
  title,
  done,
  completed,
  overdue = false,
  children,
}: {
  itemId: number;
  title: string;
  done: boolean;
  completed: boolean;
  overdue?: boolean;
  children: ReactNode;
}) {
  const hold = useDoneHold();
  const [checked, setChecked] = useState(done || completed);
  const [phase, setPhase] = useState<Phase>("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const release = useRef<((changed: boolean) => void) | null>(null);
  const timers = useRef<number[]>([]);
  const sequence = useRef(0);

  const clearTimers = () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
  };

  useEffect(
    () => () => {
      // Navigating away mid-Undo: the mark is already saved, so refresh.
      clearTimers();
      release.current?.(true);
      release.current = null;
    },
    [],
  );

  async function markDone() {
    const run = ++sequence.current;
    setError(null);
    setChecked(true);
    setPhase("undo");
    release.current?.(false);
    const releaseHold = hold();
    release.current = releaseHold;
    const result = await setItemDone(itemId, true);
    if (run !== sequence.current) return; // undone meanwhile
    if (!result.ok) {
      setChecked(false);
      setPhase("idle");
      setError(result.message);
      release.current = null;
      releaseHold(false);
      return;
    }
    timers.current.push(
      window.setTimeout(() => {
        setPhase("leaving");
        timers.current.push(
          window.setTimeout(() => {
            setPhase("gone");
            release.current = null;
            releaseHold(true);
          }, LEAVE_MS),
        );
      }, UNDO_MS),
    );
  }

  async function undo() {
    sequence.current += 1;
    clearTimers();
    setPhase("idle");
    setChecked(false);
    const releaseHold = release.current;
    release.current = null;
    const result = await setItemDone(itemId, false);
    if (!result.ok) setError(result.message);
    releaseHold?.(!result.ok);
  }

  async function unmark() {
    setError(null);
    setChecked(false);
    setBusy(true);
    const releaseHold = hold();
    const result = await setItemDone(itemId, false);
    setBusy(false);
    if (!result.ok) {
      setChecked(true);
      setError(result.message);
      releaseHold(false);
      return;
    }
    releaseHold(true);
  }

  function toggle() {
    if (phase === "undo") return void undo();
    if (checked) return void unmark();
    return void markDone();
  }

  if (phase === "gone") return null;

  const classes = ["row"];
  if (checked) classes.push("is-checked");
  if (phase === "undo") classes.push("is-undo");
  if (phase === "leaving") classes.push("is-leaving");
  if (overdue && !checked) classes.push("is-overdue");

  return (
    <li className={classes.join(" ")} id={`item-${itemId}`}>
      <div className="row-clip">
        <div className="row-inner">
          {completed ? (
            <span className="check is-static" role="img" aria-label="Completed in Canvas" title="Completed in Canvas">
              <CheckMark />
            </span>
          ) : (
            <button
              type="button"
              className="check"
              role="checkbox"
              aria-checked={checked}
              aria-label={`Done: ${title}`}
              disabled={busy || phase === "leaving"}
              onClick={toggle}
            >
              <CheckMark />
            </button>
          )}
          <div className="row-content">{children}</div>
          {phase === "undo" ? (
            <div className="row-undo">
              <span className="row-undo-label">Done</span>
              <button type="button" className="undo-button" onClick={() => void undo()}>
                Undo<span className="visually-hidden">: {title}</span>
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <span className="visually-hidden" aria-live="polite">
        {phase === "undo" ? `Marked ${title} done.` : ""}
      </span>
      {error ? (
        <p className="row-error" role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}
