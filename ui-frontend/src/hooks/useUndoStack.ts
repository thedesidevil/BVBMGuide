import { useState, useCallback } from "react";

interface UndoEntry {
  description: string;
  undo: () => void;
}

export function useUndoStack() {
  const [stack, setStack] = useState<UndoEntry[]>([]);

  const push = useCallback((entry: UndoEntry) => {
    setStack((prev) => [...prev, entry]);
  }, []);

  const undo = useCallback(() => {
    setStack((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1];
      last.undo();
      return prev.slice(0, -1);
    });
  }, []);

  const clear = useCallback(() => setStack([]), []);

  return { canUndo: stack.length > 0, undo, push, clear, count: stack.length };
}
