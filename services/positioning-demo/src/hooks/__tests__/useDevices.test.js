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

describe("useDevices", () => {
  it("returns the registry list with palette colours assigned", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        devices: [
          { phoneNumber: "+390111", deviceId: "a", label: "A" },
          { phoneNumber: "+390222", deviceId: "b", label: "B" },
        ],
      }),
    });

    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.devices).toHaveLength(2);
    expect(result.current.devices[0]).toMatchObject({
      phoneNumber: "+390111",
      deviceId: "a",
      label: "A",
    });
    expect(result.current.devices[0].color).toMatch(/^#/);
    expect(result.current.devices[1].color).toMatch(/^#/);
  });

  it("falls back to deviceId when label is missing", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ devices: [{ phoneNumber: "+390111", deviceId: "asset-x" }] }),
    });

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
    fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        devices: [
          { phoneNumber: "+390001", deviceId: "real",  label: "Real" },
          { phoneNumber: "+390002", deviceId: "mocky", label: "Mock", simulated: true },
        ],
      }),
    });
    const { result } = renderHook(() => useDevices("tok"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const byId = Object.fromEntries(result.current.devices.map((d) => [d.deviceId, d]));
    expect(byId.real.simulated).toBe(false);
    expect(byId.mocky.simulated).toBe(true);
  });
});
