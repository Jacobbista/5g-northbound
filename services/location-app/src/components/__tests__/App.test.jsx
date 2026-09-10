import { describe, it, expect } from "vitest";
import { deviceState } from "../App.jsx";

// One function serves both the sidebar row and the detail pill, so the two can
// never disagree about the same asset.
describe("deviceState", () => {
  const fresh = () => new Date().toISOString();
  const old = "2026-08-31T12:34:01Z";

  it("does not call a device live when the only signal is the broadcast tick", () => {
    // The bug this guards: a wittra tag whose fix froze days ago rendered LIVE
    // beside its own "stale" fix age, because observedAt is renewed on every
    // tick for as long as the vendor answers.
    const position = { observedAt: fresh(), lastLocationTime: old, area: { radius: 1.0 } };
    expect(deviceState({ position, deviceId: "d1" })).toBe("stale");
  });

  it("stays live when the fix itself is fresh", () => {
    const position = { observedAt: fresh(), lastLocationTime: fresh(), area: { radius: 1.0 } };
    expect(deviceState({ position, deviceId: "d2" })).toBe("live");
  });

  it("reports offline with no signal at all", () => {
    expect(deviceState({ position: {}, deviceId: "d3" })).toBe("offline");
  });

  it("flags an imprecise fix even when it is fresh", () => {
    const position = { lastLocationTime: fresh(), area: { radius: 999 } };
    expect(deviceState({ position, deviceId: "d4" })).toBe("imprecise");
  });
});
