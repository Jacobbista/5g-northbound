import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { blueprintToCanvas, canvasToBlueprint } from "./blueprintFrame.js";

// The same venue in version 2 (canvas axes) and version 3, shared with the
// engine migration tests.
// Tests run from the package root, services/placement-editor/frontend.
const examples = resolve(process.cwd(), "../../../schema/examples");
const load = (name) => JSON.parse(readFileSync(resolve(examples, name), "utf8"));
const v3 = load("layout.example.json");
const { room_w, room_h, aps, gps_origin, walls, floor_plan_image, ...v2 } = {
  ...load("layout.v2.example.json"),
  version: 2,
};

describe("blueprintFrame", () => {
  it("draws a version 3 blueprint in canvas axes", () => {
    expect(blueprintToCanvas(v3)).toEqual(v2);
  });

  it("writes the canvas model back as version 3", () => {
    expect(canvasToBlueprint(v2)).toEqual(v3);
  });

  it("leaves the input untouched", () => {
    const before = JSON.stringify(v3);
    blueprintToCanvas(v3);
    expect(JSON.stringify(v3)).toBe(before);
  });

  it("writes no z for an anchor whose height is not measured", () => {
    const model = {
      version: 2,
      floor_plans: [{ id: "fp", georef: { width_m: 10, height_m: 10 } }],
      rooms: [{ id: "r", floor_plan_id: "fp", x_m: 0, y_m: 0, width_m: 10, height_m: 10,
        anchors: [{ id: "a", x: 1, y: 1, height_m: null }, { id: "b", x: 1, y: 1 }] }],
    };
    const anchors = canvasToBlueprint(model).rooms[0].anchors;
    expect(anchors.every((a) => !("z" in a))).toBe(true);
  });
});
