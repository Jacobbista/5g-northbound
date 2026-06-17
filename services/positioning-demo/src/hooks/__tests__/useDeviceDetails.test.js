import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDeviceDetails } from "../useDeviceDetails";

const MOCK_DETAILS = {
  asset_id: "pkg-4471",
  positioning_id: "wittra-tag-01",
  kind: "pallet",
  source: "wittra",
  org: "fiskarheden",
  label: "Wittra tag 01",
  telemetry: {
    latitude: 45.064,
    longitude: 7.659,
    accuracy_m: 2.4,
    altitude: 1.2,
    lastLocationTime: "2026-06-03T12:00:00Z",
    strategy: "weighted_avg",
    sources: ["wittra"],
  },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  window.__ENV__ = { VITE_CAMARA_API_BASE: "http://test-api" };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useDeviceDetails", () => {
  it("returns details after a successful fetch", async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => MOCK_DETAILS });

    const { result } = renderHook(() => useDeviceDetails("tok", "pkg-4471"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.details).toEqual(MOCK_DETAILS);
    expect(result.current.details.telemetry.sources).toEqual(["wittra"]);
  });

  it("hits the /assets/{assetId}/details route", async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => MOCK_DETAILS });

    renderHook(() => useDeviceDetails("tok", "pkg-4471"));
    await waitFor(() => expect(fetch).toHaveBeenCalled());

    const [url] = fetch.mock.calls[0];
    expect(url).toContain("/assets/pkg-4471/details");
  });

  it("does not fetch when assetId is null", () => {
    renderHook(() => useDeviceDetails("tok", null));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("treats 404 as offline (no fix), not error", async () => {
    fetch.mockResolvedValue({ ok: false, status: 404 });

    const { result } = renderHook(() => useDeviceDetails("tok", "pkg-4471"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.details).toBeNull();
  });

  it("sets error on non-404 HTTP failure", async () => {
    fetch.mockResolvedValue({ ok: false, status: 500 });

    const { result } = renderHook(() => useDeviceDetails("tok", "pkg-4471"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/500/);
    expect(result.current.details).toBeNull();
  });

  it("does not poll when paused", () => {
    renderHook(() => useDeviceDetails("tok", "pkg-4471", { paused: true }));
    expect(fetch).not.toHaveBeenCalled();
  });
});
