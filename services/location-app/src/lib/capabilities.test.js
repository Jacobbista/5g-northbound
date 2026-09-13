import { describe, expect, it } from "vitest";
import { sourcesAdvertising } from "./capabilities";

describe("sourcesAdvertising", () => {
  const adapters = [
    { name: "wittra", capabilities: { source: "wittra", diagnostics: true, placement: false } },
    { name: "synthetic", capabilities: { source: "synthetic", placement: true } },
    { name: "wifi", capabilities: { source: "wifi" } },
  ];

  it("keeps the sources whose adapter declares the capability", () => {
    expect([...sourcesAdvertising(adapters, "diagnostics")]).toEqual(["wittra"]);
    expect([...sourcesAdvertising(adapters, "placement")]).toEqual(["synthetic"]);
  });

  it("falls back to the adapter name when no source is advertised", () => {
    expect(sourcesAdvertising([{ name: "bare", capabilities: { diagnostics: true } }], "diagnostics").has("bare")).toBe(true);
  });

  it("survives an adapter list with no capabilities", () => {
    expect(sourcesAdvertising([{ name: "odd" }], "diagnostics").size).toBe(0);
    expect(sourcesAdvertising(undefined, "diagnostics").size).toBe(0);
  });
});
