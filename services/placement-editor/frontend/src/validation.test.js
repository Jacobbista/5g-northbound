import { describe, expect, it } from "vitest";
import { snap, validateLayout, wallLength } from "./validation.js";

describe("snap", () => {
  it("rounds to multiples of step", () => {
    expect(snap(3.47, 0.5)).toBeCloseTo(3.5);
    expect(snap(3.22, 0.5)).toBeCloseTo(3.0);
    expect(snap(0.74, 0.5)).toBeCloseTo(0.5);
  });

  it("passes through when step is 0 or undefined", () => {
    expect(snap(3.47, 0)).toBe(3.47);
    expect(snap(3.47)).toBe(3.47);
  });

  it("handles negatives", () => {
    expect(snap(-1.2, 0.5)).toBeCloseTo(-1.0);
  });
});

describe("validateLayout", () => {
  it("accepts a clean layout", () => {
    const layout = {
      room_w: 13,
      room_h: 32,
      aps: [
        { id: "AP01", x: 1, y: 2 },
        { id: "AP02", x: 3, y: 4 },
      ],
    };
    expect(validateLayout(layout)).toEqual([]);
  });

  it("flags non-positive room dims", () => {
    const errs = validateLayout({ room_w: 0, room_h: -1, aps: [] });
    const fields = errs.map((e) => e.field);
    expect(fields).toContain("room_w");
    expect(fields).toContain("room_h");
  });

  it("flags duplicate AP ids", () => {
    const errs = validateLayout({
      room_w: 10,
      room_h: 10,
      aps: [
        { id: "AP01", x: 0, y: 0 },
        { id: "AP01", x: 1, y: 1 },
      ],
    });
    expect(errs.some((e) => /Duplicate/.test(e.message))).toBe(true);
  });

  it("flags empty AP id", () => {
    const errs = validateLayout({
      room_w: 10,
      room_h: 10,
      aps: [{ id: "", x: 0, y: 0 }],
    });
    expect(errs.some((e) => /empty/.test(e.message))).toBe(true);
  });

  it("flags non-numeric coordinates", () => {
    const errs = validateLayout({
      room_w: 10,
      room_h: 10,
      aps: [{ id: "AP01", x: "abc", y: 1 }],
    });
    expect(errs.some((e) => /must be numbers/.test(e.message))).toBe(true);
  });

  it("returns empty array for null layout", () => {
    expect(validateLayout(null)).toEqual([]);
  });

  it("flags zero-length walls", () => {
    const errs = validateLayout({
      room_w: 10,
      room_h: 10,
      walls: [{ id: "W01", x1: 1, y1: 1, x2: 1, y2: 1 }],
    });
    expect(errs.some((e) => /zero-length/.test(e.message))).toBe(true);
  });

  it("flags duplicate wall ids", () => {
    const errs = validateLayout({
      room_w: 10,
      room_h: 10,
      walls: [
        { id: "W01", x1: 0, y1: 0, x2: 5, y2: 0 },
        { id: "W01", x1: 0, y1: 0, x2: 5, y2: 0 },
      ],
    });
    expect(errs.some((e) => /Duplicate wall/.test(e.message))).toBe(true);
  });
});

describe("wallLength", () => {
  it("computes euclidean length", () => {
    expect(wallLength({ x1: 0, y1: 0, x2: 3, y2: 4 })).toBe(5);
  });

  it("returns NaN for non-numeric coordinates", () => {
    expect(Number.isNaN(wallLength({ x1: "a", y1: 0, x2: 1, y2: 1 }))).toBe(true);
  });
});
