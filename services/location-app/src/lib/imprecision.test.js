import { afterEach, describe, expect, it } from "vitest";
import { accuracyBound, isImprecise, setAccuracyDeclarations } from "./imprecision.js";

const vocabulary = {
  classes: {
    "sub-metre": { lowerBound: 0, upperBound: 1 },
    metre: { lowerBound: 1, upperBound: 10 },
    coarse: { lowerBound: 10 },
  },
};
const adapters = [
  { name: "wittra", capabilities: { source: "wittra", accuracy_class: "sub-metre" } },
  { name: "wifi", capabilities: { source: "wifi", accuracy_class: "metre" } },
  { name: "gnss", capabilities: { source: "gnss", accuracy_class: "coarse", nominalAccuracy: 25 } },
  { name: "other", capabilities: { source: "other", accuracy_class: "coarse" } },
];

describe("imprecision", () => {
  afterEach(() => setAccuracyDeclarations([], null));

  it("judges a fix against what its own technology delivers", () => {
    setAccuracyDeclarations(adapters, vocabulary);
    // 3 m is degraded for UWB and ordinary for WiFi.
    expect(isImprecise({ sources: ["wittra"], horizontalAccuracy: 3 })).toBe(true);
    expect(isImprecise({ sources: ["wifi"], horizontalAccuracy: 3 })).toBe(false);
  });

  it("prefers the declared nominal accuracy over the class", () => {
    setAccuracyDeclarations(adapters, vocabulary);
    expect(accuracyBound({ sources: ["gnss"] })).toBe(25);
  });

  it("takes the widest bound among the fused sources", () => {
    setAccuracyDeclarations(adapters, vocabulary);
    expect(accuracyBound({ sources: ["wittra", "wifi"] })).toBe(10);
  });

  it("falls back to the deployment threshold without a known bound", () => {
    setAccuracyDeclarations(adapters, vocabulary);
    expect(accuracyBound({ sources: ["other"] })).toBe(15);
    expect(accuracyBound({ source: "unknown" })).toBe(15);
    setAccuracyDeclarations(adapters, null);
    expect(accuracyBound({ sources: ["wittra"] })).toBe(15);
  });

  it("compares the accuracy without the 1 m floor of the CAMARA radius", () => {
    setAccuracyDeclarations(adapters, vocabulary);
    const position = { source: "wittra", horizontalAccuracy: 0.4, area: { radius: 1.0 } };
    expect(isImprecise(position)).toBe(false);
  });
});
