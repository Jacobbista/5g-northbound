import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIdlePrompt } from "../useIdlePrompt";

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(document, "hidden", { value: false, configurable: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useIdlePrompt", () => {
  it("starts in active state when the tab is visible", () => {
    const { result } = renderHook(() => useIdlePrompt());
    expect(result.current.state).toBe("active");
  });

  it("starts in standby state when the tab is hidden", () => {
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    const { result } = renderHook(() => useIdlePrompt());
    expect(result.current.state).toBe("standby");
  });

  it("moves to prompting after promptAfterMs of inactivity", () => {
    const { result } = renderHook(() =>
      useIdlePrompt({ promptAfterMs: 1000, promptTimeoutMs: 500 })
    );
    act(() => {
      vi.advanceTimersByTime(1001);
    });
    expect(result.current.state).toBe("prompting");
  });

  it("moves to standby after the prompt timeout with no input", () => {
    const { result } = renderHook(() =>
      useIdlePrompt({ promptAfterMs: 1000, promptTimeoutMs: 500 })
    );
    act(() => {
      vi.advanceTimersByTime(1001 + 600);
    });
    expect(result.current.state).toBe("standby");
  });

  it("acknowledge() returns to active and resets the prompt timer", () => {
    const { result } = renderHook(() =>
      useIdlePrompt({ promptAfterMs: 1000, promptTimeoutMs: 500 })
    );
    act(() => {
      vi.advanceTimersByTime(1001);
    });
    expect(result.current.state).toBe("prompting");
    act(() => {
      result.current.acknowledge();
    });
    expect(result.current.state).toBe("active");
  });
});
