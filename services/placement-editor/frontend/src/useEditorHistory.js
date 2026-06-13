import { useCallback, useRef, useState } from "react";

// Two-stack undo/redo with a "transient" mode for drag interactions.
//
// - `commit(next)` pushes the current value onto `past` and replaces it. This
//   is the normal mutation path (add, remove, rename, snap, blur).
// - `beginTransient()` / `applyTransient(next)` / `endTransient()` are for
//   continuous interactions (pointer drag). The intermediate values are NOT
//   added to history; only the start state is pushed once on `endTransient`,
//   collapsing the whole drag into a single undoable step.
// - `undo` / `redo` move the value along the past/future axis.
// - `replace(next)` swaps the value without touching history - used after a
//   successful save to install the saved snapshot.
export function useEditorHistory(initial) {
  const [present, setPresent] = useState(initial);
  const [past, setPast] = useState([]);
  const [future, setFuture] = useState([]);
  const transientStartRef = useRef(null);

  const commit = useCallback((next) => {
    setPresent((cur) => {
      const value = typeof next === "function" ? next(cur) : next;
      if (Object.is(value, cur)) return cur;
      setPast((p) => [...p, cur]);
      setFuture([]);
      return value;
    });
  }, []);

  const beginTransient = useCallback(() => {
    setPresent((cur) => {
      transientStartRef.current = cur;
      return cur;
    });
  }, []);

  const applyTransient = useCallback((next) => {
    setPresent((cur) => (typeof next === "function" ? next(cur) : next));
  }, []);

  const endTransient = useCallback(() => {
    setPresent((cur) => {
      const start = transientStartRef.current;
      transientStartRef.current = null;
      if (start !== null && !Object.is(start, cur)) {
        setPast((p) => [...p, start]);
        setFuture([]);
      }
      return cur;
    });
  }, []);

  const undo = useCallback(() => {
    setPast((p) => {
      if (p.length === 0) return p;
      const prev = p[p.length - 1];
      setFuture((f) => [present, ...f]);
      setPresent(prev);
      return p.slice(0, -1);
    });
  }, [present]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (f.length === 0) return f;
      const next = f[0];
      setPast((p) => [...p, present]);
      setPresent(next);
      return f.slice(1);
    });
  }, [present]);

  const replace = useCallback((next) => {
    setPresent(next);
    setPast([]);
    setFuture([]);
  }, []);

  return {
    value: present,
    commit,
    beginTransient,
    applyTransient,
    endTransient,
    undo,
    redo,
    replace,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
  };
}
