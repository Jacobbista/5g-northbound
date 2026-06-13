import { useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_PROMPT_AFTER_MS = 5 * 60_000; // 5 min of no input before prompting
const DEFAULT_PROMPT_TIMEOUT_MS = 30_000;   // user has 30 s to respond
const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "touchstart", "wheel"];

// Three-state idle controller for a positioning monitor:
//   "active"    - user interacting (or tab just became visible). Hooks poll.
//   "prompting" - no input for `promptAfterMs`. UI asks "still watching?".
//   "standby"   - tab hidden, or user didn't respond to the prompt in time.
//
// We DO NOT auto-pause silently on idle: the user may be watching the
// dashboard without moving the mouse for long stretches, and silently
// stopping the position feed would be wrong. The prompt step gives the user
// a chance to keep things running without effort.
export function useIdlePrompt({
  promptAfterMs = DEFAULT_PROMPT_AFTER_MS,
  promptTimeoutMs = DEFAULT_PROMPT_TIMEOUT_MS,
} = {}) {
  const [state, setState] = useState(() => (document.hidden ? "standby" : "active"));
  const [promptRemainingMs, setPromptRemainingMs] = useState(promptTimeoutMs);

  const promptTimer = useRef(null);
  const standbyTimer = useRef(null);
  const countdownTimer = useRef(null);

  const clearAll = useCallback(() => {
    if (promptTimer.current) clearTimeout(promptTimer.current);
    if (standbyTimer.current) clearTimeout(standbyTimer.current);
    if (countdownTimer.current) clearInterval(countdownTimer.current);
    promptTimer.current = null;
    standbyTimer.current = null;
    countdownTimer.current = null;
  }, []);

  const armPromptTimer = useCallback(() => {
    clearAll();
    promptTimer.current = setTimeout(() => {
      setState("prompting");
      setPromptRemainingMs(promptTimeoutMs);
      const startedAt = Date.now();
      countdownTimer.current = setInterval(() => {
        const remaining = Math.max(0, promptTimeoutMs - (Date.now() - startedAt));
        setPromptRemainingMs(remaining);
      }, 250);
      standbyTimer.current = setTimeout(() => {
        clearAll();
        setState("standby");
      }, promptTimeoutMs);
    }, promptAfterMs);
  }, [clearAll, promptAfterMs, promptTimeoutMs]);

  const goActive = useCallback(() => {
    setState("active");
    armPromptTimer();
  }, [armPromptTimer]);

  // Imperative API the modal binds to its "still here" button.
  const acknowledge = useCallback(() => {
    goActive();
  }, [goActive]);

  useEffect(() => {
    const onActivity = () => {
      if (document.hidden) return;
      // Any input from any state brings us back to active immediately.
      goActive();
    };
    const onVisibility = () => {
      if (document.hidden) {
        clearAll();
        setState("standby");
      } else {
        goActive();
      }
    };

    if (!document.hidden) armPromptTimer();
    document.addEventListener("visibilitychange", onVisibility);
    for (const ev of ACTIVITY_EVENTS) {
      window.addEventListener(ev, onActivity, { passive: true });
    }
    return () => {
      clearAll();
      document.removeEventListener("visibilitychange", onVisibility);
      for (const ev of ACTIVITY_EVENTS) {
        window.removeEventListener(ev, onActivity);
      }
    };
  }, [armPromptTimer, clearAll, goActive]);

  return {
    state,
    promptRemainingMs,
    acknowledge,
  };
}
