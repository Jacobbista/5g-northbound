import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDevices } from "../useDevices";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  window.__ENV__ = { VITE_CAMARA_API_BASE: "http://test-api" };
});

afterEach(() => {
  vi.restoreAllMocks();
});

function assetMap(assets) {
  return { ok: true, json: async () => ({ version: 2, assets }) };
}

describe("useDevices", () => {
  it("returns the asset map with palette colours assigned", async () => {
    fetch.mockResolvedValue(
      assetMap([
        { asset_id: "tool-880", positioning_id: "a", kind: "tool", source: "wifi", org: "x", label: "A" },
        { asset_id: "pkg-4471", positioning_id: "b", kind: "pallet", source: "wittra", org: "x", label: "B" },
      ])
    );

    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.devices).toHaveLength(2);
    expect(result.current.devices[0]).toMatchObject({
      assetId: "tool-880",
      positioningId: "a",
      kind: "tool",
      source: "wifi",
      label: "A",
    });
    expect(result.current.devices[0].color).toMatch(/^#/);
    expect(result.current.devices[1].color).toMatch(/^#/);
  });

  it("falls back to asset_id when label is missing", async () => {
    fetch.mockResolvedValue(
      assetMap([{ asset_id: "asset-x", positioning_id: "p", kind: "tool", source: "wifi", org: "x" }])
    );

    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.devices[0].label).toBe("asset-x");
  });

  it("does not fetch when token is null", () => {
    renderHook(() => useDevices(null));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("sets error on HTTP failure", async () => {
    fetch.mockResolvedValue({ ok: false, status: 401 });

    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/401/);
    expect(result.current.devices).toEqual([]);
  });

  it("propagates simulated flag from the gateway response", async () => {
    fetch.mockResolvedValue(
      assetMap([
        { asset_id: "real", positioning_id: "r", kind: "tool", source: "wifi", org: "x", label: "Real" },
        { asset_id: "mocky", positioning_id: "m", kind: "forklift", source: "mock", org: "x", label: "Mock", simulated: true },
      ])
    );
    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const byId = Object.fromEntries(result.current.devices.map((d) => [d.assetId, d]));
    expect(byId.real.simulated).toBe(false);
    expect(byId.mocky.simulated).toBe(true);
  });
});
