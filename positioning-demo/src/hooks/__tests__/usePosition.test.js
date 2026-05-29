import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePosition } from "../usePosition";

const MOCK_POSITION = {
  lastLocationTime: "2024-01-01T12:00:00Z",
  area: { areaType: "CIRCLE", center: { latitude: 45.064312, longitude: 7.659154 }, radius: 50 },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  window.__ENV__ = { VITE_CAMARA_API_BASE: "http://test-api" };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("usePosition", () => {
  it("returns position after successful fetch", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => MOCK_POSITION,
    });

    const { result } = renderHook(() => usePosition("fake-token"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.position).toEqual(MOCK_POSITION);
    expect(result.current.error).toBeNull();
  });

  it("calls the CAMARA v0.5 retrieve route with a phoneNumber device", async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => MOCK_POSITION });

    renderHook(() => usePosition("fake-token"));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const [url, opts] = fetch.mock.calls[0];
    expect(url).toMatch(/\/location-retrieval\/v0\.5\/retrieve$/);
    expect(JSON.parse(opts.body).device).toHaveProperty("phoneNumber");
  });

  it("sets error on HTTP failure", async () => {
    fetch.mockResolvedValue({ ok: false, status: 502 });

    const { result } = renderHook(() => usePosition("fake-token"));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/502/);
    expect(result.current.position).toBeNull();
  });

  it("does not fetch when token is null", () => {
    const { result } = renderHook(() => usePosition(null));
    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(true);
  });
});
