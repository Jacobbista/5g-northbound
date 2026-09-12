import { describe, it, expect, vi, beforeEach } from "vitest";
import { placeAsset, removeAsset, placeableSources } from "./placement";

beforeEach(() => {
  global.fetch = vi.fn();
});

describe("placeableSources", () => {
  it("keeps only sources that advertise placement", () => {
    const set = placeableSources([
      { name: "synthetic", capabilities: { source: "synthetic", placement: true } },
      { name: "wittra", capabilities: { source: "wittra" } },
    ]);
    expect(set.has("synthetic")).toBe(true);
    // A measured source has nothing to place.
    expect(set.has("wittra")).toBe(false);
  });

  it("survives an adapter list with no capabilities", () => {
    expect(placeableSources([{ name: "odd" }]).size).toBe(0);
    expect(placeableSources().size).toBe(0);
  });
});

describe("placeAsset", () => {
  it("sends the point to the asset-shaped surface", async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ assetId: "a", x: 4, z: 9, placed: true }) });
    await placeAsset("tok", "forklift-7", { x: 4, z: 9 });
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toMatch(/\/assets\/forklift-7\/placement$/);
    expect(opts.method).toBe("PUT");
    expect(JSON.parse(opts.body)).toEqual({ x: 4, z: 9 });
    expect(opts.headers.Authorization).toBe("Bearer tok");
  });

  it("surfaces the gateway's own refusal message", async () => {
    // A bare status tells the operator nothing they can act on.
    global.fetch.mockResolvedValue({
      ok: false, status: 422,
      json: async () => ({ code: "NOT_PLACEABLE", message: "source 'wittra' reports a measured position and cannot be placed." }),
    });
    await expect(placeAsset("tok", "pkg-4471", { x: 1, z: 1 })).rejects.toThrow(/cannot be placed/);
  });

  it("falls back to the status when the error body is not JSON", async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 502, json: async () => { throw new Error("no"); } });
    await expect(placeAsset("tok", "a", { x: 1, z: 1 })).rejects.toThrow(/502/);
  });
});

describe("removeAsset", () => {
  it("deletes without a body", async () => {
    global.fetch.mockResolvedValue({ ok: true, json: async () => ({ assetId: "a", placed: false }) });
    await removeAsset("tok", "forklift-7");
    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.method).toBe("DELETE");
    expect(opts.body).toBeUndefined();
  });
});
