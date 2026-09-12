import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DeviceItem } from "../App.jsx";

const device = { assetId: "forklift-7", label: "Synthetic demo 01", kind: "forklift", source: "synthetic", color: "#5dffb0" };
const fix = { lastLocationTime: new Date().toISOString(), area: { radius: 1.5, center: { latitude: 59.4, longitude: 17.9 } } };
const noop = () => {};

function row(props) {
  return render(
    <DeviceItem device={device} shown detailOpen={false} onOpenDetail={noop}
      onToggleShown={noop} frame={null} {...props} />
  );
}

describe("DeviceItem placement control", () => {
  it("offers to place an asset that is not on the plan", () => {
    row({ placeable: true, placed: false, position: null });
    expect(screen.getByLabelText(/place on the floor plan/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/take off/i)).not.toBeInTheDocument();
  });

  it("offers to take off an asset that is on the plan", () => {
    row({ placeable: true, placed: true, position: fix });
    expect(screen.getByLabelText(/take off the floor plan/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/place on/i)).not.toBeInTheDocument();
  });

  it("offers neither for a source that measures its own position", () => {
    // There is nothing to place: its hardware is already somewhere.
    row({ placeable: false, placed: false, position: null });
    expect(screen.queryByLabelText(/place on the floor plan/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/take off/i)).not.toBeInTheDocument();
  });

  it("still offers to place an asset whose last fix went stale", () => {
    // The bug this guards: keying on a position being present left an asset
    // stuck after removal, since the app keeps the last known fix. A stale fix
    // is not being on the plan.
    row({ placeable: true, placed: false, position: fix });
    expect(screen.getByLabelText(/place on the floor plan/i)).toBeInTheDocument();
  });

  it("starts a placement without opening the detail panel", () => {
    const onPlace = vi.fn();
    const onOpenDetail = vi.fn();
    render(
      <DeviceItem device={device} shown detailOpen={false} onOpenDetail={onOpenDetail}
        onToggleShown={noop} frame={null} placeable placed={false} position={null} onPlace={onPlace} />
    );
    screen.getByLabelText(/place on the floor plan/i).click();
    expect(onPlace).toHaveBeenCalledWith("forklift-7");
    expect(onOpenDetail).not.toHaveBeenCalled();
  });
});

describe("DeviceItem while a placement is under way", () => {
  it("offers to put it away rather than to place it again", () => {
    // The block is already out there floating. Offering to place it a second
    // time would be a second way to do what moving it already does.
    row({ placeable: true, placed: false, placing: true, position: null });
    expect(screen.getByLabelText(/cancel placing/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/place on the floor plan/i)).not.toBeInTheDocument();
  });

  it("cancels instead of removing, since nothing was placed yet", () => {
    const onCancelPlace = vi.fn();
    const onRemove = vi.fn();
    row({ placeable: true, placed: false, placing: true, position: null, onCancelPlace, onRemove });
    screen.getByLabelText(/cancel placing/i).click();
    expect(onCancelPlace).toHaveBeenCalled();
    expect(onRemove).not.toHaveBeenCalled();
  });
});
