import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DetailPanel } from "../DetailPanel.jsx";

// Stub the anchor-calibration hook (network).
vi.mock("../../hooks/useAnchorCalibration", () => ({
  useAnchorCalibration: () => ({}),
}));

const apSelection = (ap) => ({ kind: "ap", ap });

describe("DetailPanel · anchor identity (P1)", () => {
  it("shows the real vendor hardware id and device class", () => {
    render(
      <DetailPanel
        selection={apSelection({
          id: "AP01",
          technology: "wittra",
          x: 3.2,
          y: 7.1,
          height_m: 2.4,
          vendor: "wittra",
          model: "beacon",
          vendor_device_id: "DEVTAG00000000001",
        })}
        token="t"
        coordMode="relative"
        onClose={() => {}}
      />
    );
    expect(screen.getByText("hardware id")).toBeInTheDocument();
    expect(screen.getByText("DEVTAG00000000001")).toBeInTheDocument();
    expect(screen.getByText("class")).toBeInTheDocument();
    expect(screen.getByText("beacon")).toBeInTheDocument();
    // subtitle carries vendor + class
    expect(screen.getByText("wittra · beacon")).toBeInTheDocument();
  });

  it("omits the identity section for an anchor with no vendor identity", () => {
    render(
      <DetailPanel
        selection={apSelection({ id: "AP02", technology: "wifi", x: 1, y: 1 })}
        token="t"
        coordMode="relative"
        onClose={() => {}}
      />
    );
    expect(screen.queryByText("hardware id")).not.toBeInTheDocument();
    // generic subtitle
    expect(screen.getByText("Anchor · wifi")).toBeInTheDocument();
  });
});
