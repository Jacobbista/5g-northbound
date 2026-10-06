import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePositionsStream } from "../usePositionsStream";

class FakeSocket {
  static instances = [];
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    FakeSocket.instances.push(this);
  }
  close() {}
  open() { this.onopen?.(); }
  message(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
  closeWith(code) { this.onclose?.({ code }); }
}

describe("usePositionsStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("stops reconnecting when the gateway refuses the token", () => {
    const { result } = renderHook(() => usePositionsStream("tok"));
    act(() => {
      FakeSocket.instances[0].open();
      FakeSocket.instances[0].closeWith(4401);
    });
    act(() => vi.advanceTimersByTime(60_000));
    expect(FakeSocket.instances).toHaveLength(1);
    expect(result.current).toMatchObject({ connected: false, refused: true });
  });

  it("opens again when the token changes after a refusal", () => {
    const { result, rerender } = renderHook(({ token }) => usePositionsStream(token), {
      initialProps: { token: "old" },
    });
    act(() => FakeSocket.instances[0].closeWith(4401));
    rerender({ token: "new" });
    expect(FakeSocket.instances).toHaveLength(2);
    expect(FakeSocket.instances[1].protocols).toEqual(["bearer.jwt", "new"]);
    expect(result.current.refused).toBe(false);
  });

  it("keeps backing off while the handshake succeeds but no message arrives", () => {
    renderHook(() => usePositionsStream("tok"));
    const cycle = () => {
      const ws = FakeSocket.instances.at(-1);
      act(() => {
        ws.open();
        ws.closeWith(1011);
      });
    };
    cycle();
    act(() => vi.advanceTimersByTime(500));
    cycle();
    act(() => vi.advanceTimersByTime(500));
    expect(FakeSocket.instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(500));
    expect(FakeSocket.instances).toHaveLength(3);
  });

  it("resets the backoff after a message", () => {
    renderHook(() => usePositionsStream("tok"));
    act(() => FakeSocket.instances[0].closeWith(1011));
    act(() => vi.advanceTimersByTime(500));
    act(() => {
      FakeSocket.instances[1].message([]);
      FakeSocket.instances[1].closeWith(1011);
    });
    act(() => vi.advanceTimersByTime(500));
    expect(FakeSocket.instances).toHaveLength(3);
  });
});
