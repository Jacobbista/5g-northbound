import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDeviceDiagnostics } from "../useDeviceDiagnostics";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  window.__ENV__ = { VITE_CAMARA_API_BASE: "http://test-api" };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useDeviceDiagnostics", () => {
  it("asks the gateway for a source that serves diagnostics", async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ diagnostics: { battery: 80 } }) });
    const { result } = renderHook(() => useDeviceDiagnostics("tok", "pkg-1", true));
    await waitFor(() => expect(result.current.diagnostics).toEqual({ battery: 80 }));
    expect(fetch.mock.calls[0][0]).toMatch(/\/device-diagnostics\/v0\/pkg-1$/);
  });

  it("does not ask for a source that does not serve them", async () => {
    const { result } = renderHook(() => useDeviceDiagnostics("tok", "forklift-7", false));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.diagnostics).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("asks once the source turns out to serve them", async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ diagnostics: { battery: 51 } }) });
    const { result, rerender } = renderHook(
      ({ enabled }) => useDeviceDiagnostics("tok", "pkg-1", enabled),
      { initialProps: { enabled: false } }
    );
    expect(fetch).not.toHaveBeenCalled();
    // The adapter list arrives after the selection: the answer follows it.
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.diagnostics).toEqual({ battery: 51 }));
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
