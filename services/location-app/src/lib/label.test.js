import { describe, it, expect } from "vitest";
import { shortLabel } from "./label.js";

describe("shortLabel", () => {
  it("passes a short id through unchanged", () => {
    expect(shortLabel("AP01")).toBe("AP01");
    expect(shortLabel("puppypi-01")).toBe("puppypi-01");
  });

  it("keeps the trailing chars of a long id behind an ellipsis", () => {
    expect(shortLabel("DEVTAG00000000001")).toBe("…000001");
  });

  it("honours custom max/keep", () => {
    expect(shortLabel("abcdefghij", { max: 4, keep: 3 })).toBe("…hij");
  });

  it("is safe on null/undefined", () => {
    expect(shortLabel(null)).toBe("");
    expect(shortLabel(undefined)).toBe("");
  });
});
