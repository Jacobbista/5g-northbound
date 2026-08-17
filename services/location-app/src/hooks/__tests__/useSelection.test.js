import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useSelection } from "../useSelection";

const KEY = "5g-location-app.selection.v1";

beforeEach(() => {
  localStorage.clear();
});

describe("useSelection", () => {
  it("defaults to all devices selected on first run", () => {
    const phones = ["+1", "+2", "+3"];
    const { result } = renderHook(() => useSelection(phones));
    expect(result.current.isSelected("+1")).toBe(true);
    expect(result.current.isSelected("+2")).toBe(true);
  });

  it("persists toggled selection across hook re-mounts", () => {
    const phones = ["+1", "+2"];
    const { result, unmount } = renderHook(() => useSelection(phones));

    act(() => result.current.toggle("+2"));
    expect(result.current.isSelected("+2")).toBe(false);

    unmount();

    const second = renderHook(() => useSelection(phones));
    expect(second.result.current.isSelected("+1")).toBe(true);
    expect(second.result.current.isSelected("+2")).toBe(false);
  });

  it("toggle adds a previously-deselected phone back", () => {
    const phones = ["+1"];
    const { result } = renderHook(() => useSelection(phones));

    act(() => result.current.toggle("+1"));
    expect(result.current.isSelected("+1")).toBe(false);

    act(() => result.current.toggle("+1"));
    expect(result.current.isSelected("+1")).toBe(true);
  });

  it("ignores corrupted localStorage and resets to default", () => {
    localStorage.setItem(KEY, "{not-json");
    const { result } = renderHook(() => useSelection(["+1"]));
    expect(result.current.isSelected("+1")).toBe(true);
  });
});
