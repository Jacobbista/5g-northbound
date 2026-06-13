import { useEffect, useState } from "react";

const STORAGE_KEY = "5g-positioning-demo.selection.v1";

// Tracks which devices the user wants to follow. Persisted per-browser via
// localStorage so a refresh keeps the same set. Devices unknown to the
// registry at load time stay deselected until the user opts in.
export function useSelection(allPhones) {
  const [selected, setSelected] = useState(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return new Set(JSON.parse(raw));
    } catch {
      // ignore corrupted localStorage
    }
    return null; // sentinel: default to "all selected" once devices known
  });

  useEffect(() => {
    if (selected === null && allPhones.length > 0) {
      setSelected(new Set(allPhones));
    }
  }, [allPhones, selected]);

  useEffect(() => {
    if (selected !== null) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...selected]));
      } catch {
        // ignore quota errors
      }
    }
  }, [selected]);

  const toggle = (phone) =>
    setSelected((prev) => {
      const next = new Set(prev || []);
      if (next.has(phone)) next.delete(phone);
      else next.add(phone);
      return next;
    });

  const isSelected = (phone) => (selected === null ? true : selected.has(phone));

  return { isSelected, toggle };
}
