"use client";

import { createContext, useCallback, useContext, useRef, useTransition, type ReactNode } from "react";

import { refreshViews } from "../actions";

/** Returns a release function; pass true when the server state changed. */
type Hold = () => (changed: boolean) => void;

const DoneContext = createContext<Hold>(() => () => {});

/**
 * Coordinates the refresh after items are marked done. Each row holds the
 * page while its Undo is showing; the pages are revalidated once the last
 * hold is released, so marking several items in a row never removes a row
 * whose Undo is still on screen.
 */
export function DoneProvider({ children }: { children: ReactNode }) {
  const holds = useRef(0);
  const dirty = useRef(false);
  const [, startTransition] = useTransition();

  const hold = useCallback<Hold>(() => {
    holds.current += 1;
    let released = false;
    return (changed: boolean) => {
      if (released) return;
      released = true;
      holds.current -= 1;
      if (changed) dirty.current = true;
      if (holds.current === 0 && dirty.current) {
        dirty.current = false;
        startTransition(() => refreshViews());
      }
    };
  }, []);

  return <DoneContext.Provider value={hold}>{children}</DoneContext.Provider>;
}

export function useDoneHold(): Hold {
  return useContext(DoneContext);
}
