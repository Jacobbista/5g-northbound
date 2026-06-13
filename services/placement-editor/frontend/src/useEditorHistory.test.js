import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useEditorHistory } from "./useEditorHistory.js";

const initial = { room_w: 10, room_h: 10, aps: [] };

describe("useEditorHistory", () => {
  it("starts with initial value and no history", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    expect(result.current.value).toEqual(initial);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("commit pushes onto past; undo restores prior value", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.commit({ ...initial, room_w: 20 }));
    expect(result.current.value.room_w).toBe(20);
    expect(result.current.canUndo).toBe(true);

    act(() => result.current.undo());
    expect(result.current.value).toEqual(initial);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(true);
  });

  it("redo re-applies the undone value", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.commit({ ...initial, room_w: 20 }));
    act(() => result.current.undo());
    act(() => result.current.redo());
    expect(result.current.value.room_w).toBe(20);
    expect(result.current.canRedo).toBe(false);
  });

  it("new commit after undo clears the future stack", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.commit({ ...initial, room_w: 20 }));
    act(() => result.current.undo());
    act(() => result.current.commit({ ...initial, room_w: 30 }));
    expect(result.current.canRedo).toBe(false);
    expect(result.current.value.room_w).toBe(30);
  });

  it("transient interactions collapse into a single history step", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.beginTransient());
    act(() => result.current.applyTransient({ ...initial, room_w: 11 }));
    act(() => result.current.applyTransient({ ...initial, room_w: 12 }));
    act(() => result.current.applyTransient({ ...initial, room_w: 13 }));
    act(() => result.current.endTransient());
    expect(result.current.value.room_w).toBe(13);

    act(() => result.current.undo());
    // Should restore the value from before the transient series began.
    expect(result.current.value).toEqual(initial);
  });

  it("endTransient without change does not push onto history", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.beginTransient());
    act(() => result.current.endTransient());
    expect(result.current.canUndo).toBe(false);
  });

  it("replace swaps the value and clears history", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.commit({ ...initial, room_w: 20 }));
    act(() => result.current.replace({ ...initial, room_w: 99 }));
    expect(result.current.value.room_w).toBe(99);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("commit with identity function does not push onto history", () => {
    const { result } = renderHook(() => useEditorHistory(initial));
    act(() => result.current.commit((cur) => cur));
    expect(result.current.canUndo).toBe(false);
  });
});
