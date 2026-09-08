import { describe, it, expect, beforeEach } from "vitest";
import {
  STALE_CAP_SECS,
  STALE_FLOOR_SECS,
  appendGap,
  gapsFor,
  livenessFor,
  median,
  recordLastSeen,
  resetLiveness,
  staleBoundSecs,
} from "./liveness";

const iso = (secs) => new Date(secs * 1000).toISOString();

beforeEach(() => resetLiveness());

describe("median", () => {
  it("handles odd and even lengths, and no samples", () => {
    expect(median([5])).toBe(5);
    expect(median([1, 9, 5])).toBe(5);
    expect(median([1, 3, 5, 7])).toBe(4);
    expect(median([])).toBeNull();
  });
});

describe("staleBoundSecs", () => {
  it("falls back to the cap with no learned rhythm", () => {
    // An unknown cadence must not flag a slow reporter as dead.
    expect(staleBoundSecs([])).toBe(STALE_CAP_SECS);
  });

  it("scales with the device's own typical gap", () => {
    // A tag reporting every 300s tolerates 900s of silence.
    expect(staleBoundSecs([300, 300, 300])).toBe(900);
  });

  it("clamps to the floor so one missed report never flags a fast mover", () => {
    // Reporting every 2s would give a 6s bound; the floor protects it.
    expect(staleBoundSecs([2, 2, 2])).toBe(STALE_FLOOR_SECS);
  });

  it("clamps to the cap so a very slow reporter is still flagged when dead", () => {
    expect(staleBoundSecs([100000])).toBe(STALE_CAP_SECS);
  });
});

describe("appendGap", () => {
  it("records forward progress only", () => {
    expect(appendGap([], 100, 160)).toEqual([60]);
    // Same value re-arriving, or going backwards, is not a new report.
    expect(appendGap([60], 160, 160)).toEqual([60]);
    expect(appendGap([60], 160, 100)).toEqual([60]);
  });

  it("keeps only the most recent samples so a rhythm change re-calibrates", () => {
    let gaps = [];
    for (let i = 1; i <= 15; i++) gaps = appendGap(gaps, i * 10, i * 10 + 5);
    expect(gaps.length).toBe(10);
  });
});

describe("recordLastSeen", () => {
  it("learns gaps from changed values, ignoring repeats on every tick", () => {
    recordLastSeen("d1", iso(1000));
    recordLastSeen("d1", iso(1000)); // same value re-broadcast
    recordLastSeen("d1", iso(1300));
    expect(gapsFor("d1")).toEqual([300]);
  });

  it("ignores a missing id or value", () => {
    recordLastSeen(null, iso(1000));
    recordLastSeen("d2", null);
    expect(gapsFor("d2")).toEqual([]);
  });
});

describe("livenessFor", () => {
  it("is offline when the source reports no last communication", () => {
    expect(livenessFor("d1", null)).toBe("offline");
  });

  it("keeps a slow but reporting device live", () => {
    // Reports every 300s; 200s of silence is well within its rhythm.
    recordLastSeen("d1", iso(1000));
    recordLastSeen("d1", iso(1300));
    recordLastSeen("d1", iso(1600));
    expect(livenessFor("d1", iso(1600), 1800 * 1000)).toBe("live");
  });

  it("marks a long-silent device stale even though it once reported slowly", () => {
    // The wittra case: last communication 6 days ago.
    recordLastSeen("d1", iso(1000));
    recordLastSeen("d1", iso(1300));
    const sixDaysLater = (1300 + 6 * 86400) * 1000;
    expect(livenessFor("d1", iso(1300), sixDaysLater)).toBe("stale");
  });

  it("does not flag a fast mover on a single missed report", () => {
    recordLastSeen("d1", iso(1000));
    recordLastSeen("d1", iso(1002));
    // 10s of silence, under the floor.
    expect(livenessFor("d1", iso(1002), 1012 * 1000)).toBe("live");
  });
});
