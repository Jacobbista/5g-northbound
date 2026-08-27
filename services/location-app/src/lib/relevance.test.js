import { describe, it, expect } from "vitest";
import { relevantAnchorIds } from "./relevance.js";

const anchors = [
  { id: "AP01", technology: "wittra", vendor_device_id: "VDR-1" },
  { id: "AP02", technology: "wittra", vendor_device_id: "VDR-2" },
  { id: "AP03", technology: "wittra", vendor_device_id: "VDR-3" },
  { id: "AP04", technology: "wifi" },
];

describe("relevantAnchorIds", () => {
  it("returns null when there is no focus (no filter, neutral scene)", () => {
    expect(relevantAnchorIds(null, anchors)).toBeNull();
  });

  it("selects UWB anchors by neighbor vendor_device_id", () => {
    const focus = { technology: "wittra", neighbors: ["VDR-1", "VDR-3"] };
    expect(relevantAnchorIds(focus, anchors)).toEqual(new Set(["AP01", "AP03"]));
  });

  it("falls back to the technology set when neighbors are absent", () => {
    const focus = { technology: "wittra" };
    expect(relevantAnchorIds(focus, anchors)).toEqual(new Set(["AP01", "AP02", "AP03"]));
  });

  it("falls back to the technology set when no neighbor matches a placed anchor", () => {
    const focus = { technology: "wittra", neighbors: ["UNKNOWN"] };
    expect(relevantAnchorIds(focus, anchors)).toEqual(new Set(["AP01", "AP02", "AP03"]));
  });

  it("uses the technology set for a wifi asset", () => {
    const focus = { technology: "wifi" };
    expect(relevantAnchorIds(focus, anchors)).toEqual(new Set(["AP04"]));
  });
});
