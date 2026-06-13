import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAdapterHealth } from "../useAdapterHealth";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  window.__ENV__ = { VITE_CAMARA_API_BASE: "http://test-api" };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useAdapterHealth", () => {
  it("returns the adapter list from the gateway", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        adapters: [
          { name: "wifi", base_url: "u", fail_count: 0, in_cooldown: false, cooldown_seconds_remaining: 0 },
          { name: "wittra", base_url: "u", fail_count: 5, in_cooldown: true, cooldown_seconds_remaining: 8 },
        ],
      }),
    });

    const { result } = renderHook(() => useAdapterHealth("tok"));
    await waitFor(() => expect(result.current).toHaveLength(2));

    expect(result.current.find((a) => a.name === "wittra").in_cooldown).toBe(true);
  });

  it("returns [] when the gateway is unreachable", async () => {
    fetch.mockRejectedValue(new Error("network"));

    const { result } = renderHook(() => useAdapterHealth("tok"));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it("does not poll when token is null", () => {
    renderHook(() => useAdapterHealth(null));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns [] when the response is empty", async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ adapters: [] }) });
    const { result } = renderHook(() => useAdapterHealth("tok"));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(result.current).toEqual([]);
  });

  it("does not poll when paused", () => {
    renderHook(() => useAdapterHealth("tok", { paused: true }));
    expect(fetch).not.toHaveBeenCalled();
  });
});
