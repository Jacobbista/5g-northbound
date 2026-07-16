import { useEffect, useState } from "react";
import { subscribeToasts } from "./toast.js";

// Per-kind accent + dwell time. Errors linger longer than confirmations.
const KIND = {
  info: { accent: "#5dffb0", ttl: 4500 },
  warn: { accent: "#ffb347", ttl: 6000 },
  error: { accent: "#ff6b78", ttl: 7000 },
};

export function ToastHost() {
  const [items, setItems] = useState([]);

  useEffect(
    () =>
      subscribeToasts((t) => {
        setItems((cur) => [...cur, t]);
        const ttl = (KIND[t.kind] ?? KIND.info).ttl;
        setTimeout(
          () => setItems((cur) => cur.filter((x) => x.id !== t.id)),
          ttl
        );
      }),
    []
  );

  const dismiss = (id) => setItems((cur) => cur.filter((x) => x.id !== id));

  if (items.length === 0) return null;
  return (
    <div
      aria-live="polite"
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        maxWidth: "min(380px, calc(100vw - 32px))",
        pointerEvents: "none",
      }}
    >
      {items.map((t) => {
        const accent = (KIND[t.kind] ?? KIND.info).accent;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => dismiss(t.id)}
            title="Dismiss"
            style={{
              pointerEvents: "auto",
              textAlign: "left",
              cursor: "pointer",
              background: "#0c1428",
              color: "#e6edf7",
              border: `1px solid ${accent}66`,
              borderLeft: `3px solid ${accent}`,
              borderRadius: 8,
              padding: "10px 12px",
              font: "inherit",
              fontSize: 13,
              lineHeight: 1.4,
              boxShadow: "0 6px 20px #00000066",
            }}
          >
            {t.message}
          </button>
        );
      })}
    </div>
  );
}
