import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CalibrationPanel } from "./CalibrationPanel.jsx";

beforeEach(() => {
  // reloadState() fires on mount when active; stub the state fetch.
  global.fetch = vi.fn(async () =>
    new Response(JSON.stringify({ samples: [], open_sessions: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

// Mounting evaluates the hook order; a use-before-declaration (TDZ) in the
// component body throws here even though the bundle builds fine.
test("renders active panel without throwing (hook order / TDZ guard)", async () => {
  render(<CalibrationPanel active={true} anchors={[]} onClose={() => {}} />);
  expect(screen.getByText(/wifi calibration/i)).toBeTruthy();
  expect(screen.getByText(/export bindings/i)).toBeTruthy();
  expect(screen.getByText(/import bindings/i)).toBeTruthy();
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
});

test("renders nothing when inactive", () => {
  const { container } = render(<CalibrationPanel active={false} anchors={[]} />);
  expect(container.firstChild).toBeNull();
});
