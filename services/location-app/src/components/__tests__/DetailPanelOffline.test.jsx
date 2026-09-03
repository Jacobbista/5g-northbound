import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DetailPanel } from "../DetailPanel.jsx";

vi.mock("../../hooks/useAnchorCalibration", () => ({
  useAnchorCalibration: () => ({}),
}));

// An offline asset: registered, but no positioning source is reporting it, so
// the details endpoint returns no telemetry.
vi.mock("../../hooks/useDeviceDetails", () => ({
  useDeviceDetails: () => ({
    details: { telemetry: null, kind: "uwb-tag", source: "wittra" },
    error: null,
    loading: false,
  }),
}));

vi.mock("../../hooks/useDeviceDiagnostics", () => ({
  useDeviceDiagnostics: () => ({ diagnostics: null, loading: false, error: null }),
}));

describe("DetailPanel · offline asset with a cached last fix", () => {
  it("reaches the detail and shows the last known fix", () => {
    render(
      <DetailPanel
        selection={{ kind: "device", device: { assetId: "pkg-1", label: "pkg-1", color: "#5dffb0", source: "wittra" } }}
        token="t"
        onClose={() => {}}
        frame={null}
        lastFix={{ area: { center: { latitude: 59.4, longitude: 17.9 } }, observedAt: "2026-09-03T10:00:00Z" }}
      />
    );
    expect(screen.getByText(/No current fix/)).toBeInTheDocument();
    expect(screen.getByText("last known fix")).toBeInTheDocument();
    expect(screen.getByText(/59\.400000, 17\.900000/)).toBeInTheDocument();
  });

  it("omits the last-fix section when nothing was ever seen", () => {
    render(
      <DetailPanel
        selection={{ kind: "device", device: { assetId: "pkg-2", label: "pkg-2", color: "#5dffb0", source: "wittra" } }}
        token="t"
        onClose={() => {}}
        frame={null}
        lastFix={null}
      />
    );
    expect(screen.getByText(/No current fix/)).toBeInTheDocument();
    expect(screen.queryByText("last known fix")).not.toBeInTheDocument();
  });
});
