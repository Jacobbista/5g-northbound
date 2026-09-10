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
  return { ok: true, json: async () => ({ version: 4, assets }) };
}

describe("useDevices", () => {
  it("returns the asset map with palette colours assigned", async () => {
    fetch.mockResolvedValue(
      assetMap([
        { assetId: "tool-880", kind: "tool", org: "x", label: "A",
          capabilities: [{ source: "wifi", positioningId: "a" }] },
        { assetId: "pkg-4471", kind: "pallet", org: "x", label: "B",
          capabilities: [{ source: "wittra", positioningId: "b" }] },
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

  it("falls back to assetId when label is missing", async () => {
    fetch.mockResolvedValue(
      assetMap([{ assetId: "asset-x", positioningId: "p", kind: "tool", source: "wifi", org: "x" }])
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

  it("derives positioningId + source from capabilities[] (asset schema v4)", async () => {
    fetch.mockResolvedValue(
      assetMap([
        {
          assetId: "forklift-7",
          kind: "forklift",
          org: "x",
          label: "Synthetic",
          capabilities: [{ source: "synthetic", positioningId: "synthetic-demo-01" }],
        },
      ])
    );
    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const d = result.current.devices[0];
    // The live-stream join key comes from the primary capability, not a flat field.
    expect(d.positioningId).toBe("synthetic-demo-01");
    expect(d.source).toBe("synthetic");
  });

  it("propagates source from the gateway response (drives the synthetic badge)", async () => {
    fetch.mockResolvedValue(
      assetMap([
        { assetId: "real", positioningId: "r", kind: "tool", source: "wifi", org: "x", label: "Real" },
        { assetId: "walker", positioningId: "m", kind: "forklift", source: "synthetic", org: "x", label: "Walker" },
      ])
    );
    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const byId = Object.fromEntries(result.current.devices.map((d) => [d.assetId, d]));
    expect(byId.real.source).toBe("wifi");
    expect(byId.walker.source).toBe("synthetic");
  });
});
