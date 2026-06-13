import { useEffect, useRef, useState } from "react";

const SNAP_M = 0.5;
const FINE_M = 0.1;
const MIN_DIM_M = 0.5;
const snap = (v, step) => (step > 0 ? Math.round(v / step) * step : v);

// Plan canvas - section 2 of the editor. Renders the floor plan image (or a
// dashed rectangle if there's none) as the metric backdrop, with the rooms
// belonging to the current floor as draggable + corner-resizable rectangles
// on top. Drag inside a room translates it; drag a corner handle resizes
// it. All gestures snap to 0.5 m and are transient-history-bracketed so the
// whole drag collapses to a single undo step.
//
// The selected room renders with strong cyan contrast + corner handles +
// live dimension labels; unselected rooms are dim orange + click-to-select.
// Picked colours (cyan/yellow) match the World step's edit palette so the
// operator's mental model is consistent across sections.
export function PlanCanvas({
  floorPlan,
  rooms,
  selectedRoomId,
  onSelectRoom,
  // Edit-mode flag. Drag-to-move + corner/edge resize handles are only
  // active when editingRoomId equals the currently-selected room. View
  // mode keeps the room visible + click-selectable but immutable on the
  // canvas (the operator can still type into numeric sidebar inputs).
  editingRoomId = null,
  onExitEdit,
  // Global toggles mirrored from the header - wired so the operator's
  // setting is honoured across all three sections, not just the World map.
  snapEnabled = true,
  showGrid = false,
  onRoomDragStart,
  onRoomDragMove,
  onRoomDragEnd,
  // Polygon-trace tool. Driven from outside (sidebar button) so the trace
  // state is visible to the rest of the editor (e.g. keyboard handlers).
  traceActive = false,
  onTraceCommit, // called with the closed polygon: shape: [[x, y], ...]
  onTraceCancel,
  // Scale-calibration tool. The parent owns the picking state machine
  // (pickingP1 / pendingP1 / pendingP2 + the refs list); the canvas
  // captures clicks, renders confirmed refs + pending pair, AND houses the
  // floating guided panel so the operator's focus stays on the image
  // instead of bouncing to the sidebar.
  //   scaleCal: null | { picking, pendingP1, pendingP2, refs: [{p1, p2, knownM, distNow}] }
  scaleCal = null,
  setScaleCal,        // React state setter - for in-flight mutations
  onScaleCalClick,    // pointer-up handler binds vertices
  onScaleCalApply,    // commit + dismiss
  // Fit-to-corners tool: two loupe-precision clicks on OPPOSITE corners of
  // the room as drawn on the image → x/y/width/height set in one shot.
  // The parent owns activation; p1 lives here in the shared state object so
  // Esc/undo semantics stay visible to the sidebar.
  //   fitCorners: null | { p1: [x, y] | null }
  fitCorners = null,
  setFitCorners,
  onFitCornersCommit, // ({x_m, y_m, width_m, height_m}) => void
}) {
  // Snap step: 0.5 m when snap is on, 0.1 m fine when off. (Truly free
  // would let any fractional value through; we keep a tiny step so values
  // stay readable in the sidebar.)
  const snapStep = snapEnabled ? SNAP_M : FINE_M;
  const svgRef = useRef(null);
  const dragRef = useRef(null);
  const panRef = useRef(null);
  // Whether the cursor is currently dragging-to-pan. Used to swap the
  // cursor between "grab" (idle) and "grabbing" (active pan).
  const [isPanning, setIsPanning] = useState(false);
  // Pixel-precision loupe - opened on every scale-calibration click so the
  // operator can refine the position against a magnified view of the floor
  // plan before committing the vertex. Shape: { initialPos, pos } in
  // floor-plan-local metres.
  const [loupe, setLoupe] = useState(null);
  const loupeSvgRef = useRef(null);
  // Trace tool - collects the polygon vertices as the operator clicks. Lives
  // in component state because it's transient draft state (nothing committed
  // until Enter / double-click / first-vertex re-click).
  const [traceVerts, setTraceVerts] = useState([]);
  const [traceCursor, setTraceCursor] = useState(null);
  // Reset draft whenever the trace mode toggles. Avoids stale vertices
  // resurfacing if the operator cancels and re-enters tracing.
  useEffect(() => {
    if (!traceActive) {
      setTraceVerts([]);
      setTraceCursor(null);
    }
  }, [traceActive]);
  // Keyboard support while tracing - Enter closes, Backspace pops the last
  // vertex, Esc cancels via the parent.
  useEffect(() => {
    if (!traceActive) return;
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        onTraceCancel?.();
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (traceVerts.length >= 3) {
          onTraceCommit?.(traceVerts);
        }
      } else if (e.key === "Backspace" || e.key === "Delete") {
        // Ignore if a text/number field has focus.
        if (
          e.target instanceof HTMLElement &&
          ["INPUT", "TEXTAREA"].includes(e.target.tagName)
        ) {
          return;
        }
        e.preventDefault();
        e.stopImmediatePropagation();
        setTraceVerts((v) => v.slice(0, -1));
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [traceActive, traceVerts, onTraceCommit, onTraceCancel]);

  // Scale-calibration keyboard. Esc has two-level cancel:
  //   loupe open  → close just the loupe (this click was a misclick)
  //   loupe closed → cancel the whole calibration
  // Enter inside the loupe = accept the precise position.
  useEffect(() => {
    if (!scaleCal) return;
    const onKey = (e) => {
      // Don't hijack typing in the known-distance input.
      if (
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA"].includes(e.target.tagName)
      ) {
        return;
      }
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        if (loupe) setLoupe(null);
        else setScaleCal?.(null);
      } else if (e.key === "Enter" && loupe) {
        e.stopImmediatePropagation();
        onScaleCalClick?.(loupe.pos);
        setLoupe(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [scaleCal, loupe, setScaleCal, onScaleCalClick]);

  // Auto-close the loupe if the owning tool gets cancelled out from under it.
  useEffect(() => {
    if (!scaleCal && !fitCorners && loupe) setLoupe(null);
  }, [scaleCal, fitCorners, loupe]);

  // Accept a loupe-refined position for the fit-to-corners tool. First
  // accept records corner 1; second computes the rectangle and commits.
  // No snap - like scale calibration, precision is the point.
  const r2 = (v) => Math.round(v * 100) / 100;
  const handleFitAccept = (pos) => {
    if (!fitCorners) return;
    if (!fitCorners.p1) {
      setFitCorners?.({ ...fitCorners, p1: pos });
      return;
    }
    const [x1, y1] = fitCorners.p1;
    const [x2, y2] = pos;
    const rect = {
      x_m: r2(Math.min(x1, x2)),
      y_m: r2(Math.min(y1, y2)),
      width_m: r2(Math.abs(x2 - x1)),
      height_m: r2(Math.abs(y2 - y1)),
    };
    if (rect.width_m < MIN_DIM_M || rect.height_m < MIN_DIM_M) {
      // Degenerate pick (same corner twice) - restart from corner 1.
      setFitCorners?.({ p1: null });
      return;
    }
    onFitCornersCommit?.(rect);
  };

  // Fit-to-corners keyboard: Esc closes the loupe first, then the tool;
  // Enter inside the loupe accepts the refined position.
  useEffect(() => {
    if (!fitCorners) return;
    const onKey = (e) => {
      if (
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA"].includes(e.target.tagName)
      ) {
        return;
      }
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        if (loupe) setLoupe(null);
        else if (fitCorners.p1) setFitCorners?.({ p1: null });
        else setFitCorners?.(null);
      } else if (e.key === "Enter" && loupe) {
        e.stopImmediatePropagation();
        handleFitAccept(loupe.pos);
        setLoupe(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [fitCorners, loupe]);

  // Arrow-key nudge for the room in edit mode: 0.1 m per press, 0.5 m with
  // Shift. Each press is one undo step. Disabled while any picking tool is
  // active so arrows never fight the loupe / trace flows.
  useEffect(() => {
    if (!editingRoomId || traceActive || scaleCal || fitCorners) return;
    const onKey = (e) => {
      if (
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA"].includes(e.target.tagName)
      ) {
        return;
      }
      const step = e.shiftKey ? SNAP_M : FINE_M;
      let dx = 0, dy = 0;
      if (e.key === "ArrowLeft") dx = -step;
      else if (e.key === "ArrowRight") dx = step;
      else if (e.key === "ArrowUp") dy = -step;
      else if (e.key === "ArrowDown") dy = step;
      else return;
      const room = rooms.find((r) => r.id === editingRoomId);
      if (!room) return;
      e.preventDefault();
      onRoomDragStart?.();
      const fields = { x_m: r2(room.x_m + dx), y_m: r2(room.y_m + dy) };
      if (Array.isArray(room.shape) && room.shape.length >= 3) {
        fields.shape = room.shape.map(([px, py]) => [r2(px + dx), r2(py + dy)]);
      }
      onRoomDragMove?.(editingRoomId, fields);
      onRoomDragEnd?.();
      setDragInfo(`${fields.x_m.toFixed(1)}, ${fields.y_m.toFixed(1)} m`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editingRoomId, rooms, traceActive, scaleCal, fitCorners, onRoomDragStart, onRoomDragMove, onRoomDragEnd]);
  // Live readout of the most recent transient mutation - shown in a small
  // pill at the top of the canvas during a drag/resize so the operator
  // sees the numeric value snap in real time.
  const [dragInfo, setDragInfo] = useState(null);

  const W = Number(floorPlan?.georef?.width_m) || 50;
  const H = Number(floorPlan?.georef?.height_m) || 50;
  const margin = Math.max(2, Math.min(W, H) * 0.05);
  // Initial / "fit" viewBox covers the floor plan + a small margin on each
  // side. `viewBox` is state so the operator can wheel-zoom and drag-pan.
  // Resetting (the fit button) jumps back to this baseline.
  const fitViewBox = { x: -margin, y: -margin, w: W + 2 * margin, h: H + 2 * margin };
  const [viewBox, setViewBox] = useState(fitViewBox);
  // Re-fit whenever the floor plan dimensions change (e.g. user re-uploads
  // a different reference image, or calibration scaled the plan).
  useEffect(() => {
    setViewBox(fitViewBox);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [W, H]);
  const vb = `${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`;
  // Current zoom factor - how many original-viewBox-widths fit in the
  // current viewBox. Used to surface a "1.0×" / "2.4×" readout next to the
  // fit button.
  const zoomFactor = fitViewBox.w / viewBox.w;

  const clientToWorld = (evt) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const local = pt.matrixTransform(ctm.inverse());
    return { x: local.x, y: local.y };
  };

  // Start a translate drag on a room. Drag only fires when this room is
  // the active edit target - otherwise the click just selects (and the
  // operator must explicitly enter edit mode from the sidebar).
  const onRoomPointerDown = (evt, room) => {
    evt.stopPropagation();
    evt.target.setPointerCapture?.(evt.pointerId);
    onSelectRoom?.(room.id);
    if (editingRoomId !== room.id) return; // view mode → select only
    const world = clientToWorld(evt);
    if (!world) return;
    dragRef.current = {
      kind: "move",
      id: room.id,
      startClientX: evt.clientX,
      startClientY: evt.clientY,
      // Offset so the grabbed point stays under the cursor (lifts the
      // first-pointermove "snap-to-cursor" bug from the World step too).
      offsetX: room.x_m - world.x,
      offsetY: room.y_m - world.y,
      // For polygon-shaped rooms, snapshot the vertices at drag-start so
      // we can translate the whole shape by the same delta as the bbox.
      startX: room.x_m,
      startY: room.y_m,
      shapeAtStart:
        Array.isArray(room.shape) && room.shape.length >= 3
          ? room.shape.map((p) => [p[0], p[1]])
          : null,
      // Dead-zone: dragging is suppressed until pointer moves past 4 px.
      started: false,
    };
  };

  // Start a corner-resize drag.
  // `cornerKey` is one of TL/TR/BL/BR. The OPPOSITE corner stays anchored
  // in world coords; width/height (and x/y if dragging top/left) recompute
  // from the cursor.
  const onCornerPointerDown = (evt, room, cornerKey) => {
    evt.stopPropagation();
    evt.target.setPointerCapture?.(evt.pointerId);
    onSelectRoom?.(room.id);
    const opp = {
      TL: { x: room.x_m + room.width_m, y: room.y_m + room.height_m },
      TR: { x: room.x_m,                 y: room.y_m + room.height_m },
      BL: { x: room.x_m + room.width_m, y: room.y_m },
      BR: { x: room.x_m,                 y: room.y_m },
    }[cornerKey];
    dragRef.current = {
      kind: "resize",
      id: room.id,
      cornerKey,
      anchorX: opp.x,
      anchorY: opp.y,
      startClientX: evt.clientX,
      startClientY: evt.clientY,
      started: false,
    };
  };

  // Start an edge-resize drag - single-axis only, so the operator can tweak
  // one dimension without disturbing the other. The opposite edge stays
  // anchored; only width OR height (and x OR y if pulling the left or top
  // edge) recompute.
  //   edgeKey ∈ "N" | "S" | "E" | "W"
  //     N = top edge,  drag down ⇒ height shrinks + y_m shifts down
  //     S = bot edge,  drag down ⇒ height grows
  //     W = left edge, drag right ⇒ width shrinks + x_m shifts right
  //     E = right edge, drag right ⇒ width grows
  const onEdgePointerDown = (evt, room, edgeKey) => {
    evt.stopPropagation();
    evt.target.setPointerCapture?.(evt.pointerId);
    onSelectRoom?.(room.id);
    const anchor = {
      N: { y: room.y_m + room.height_m },
      S: { y: room.y_m },
      W: { x: room.x_m + room.width_m },
      E: { x: room.x_m },
    }[edgeKey];
    dragRef.current = {
      kind: "edge",
      id: room.id,
      edgeKey,
      anchorX: anchor.x,
      anchorY: anchor.y,
      // For E/W drags, height/y_m stay; for N/S, width/x_m stay. Snapshot
      // them so we don't accidentally pick up live values during the drag.
      keepX: room.x_m,
      keepY: room.y_m,
      keepW: room.width_m,
      keepH: room.height_m,
      startClientX: evt.clientX,
      startClientY: evt.clientY,
      started: false,
    };
  };

  const onPointerMove = (evt) => {
    // Track the cursor in world coords during any picker-style tool
    // (polygon trace, scale calibration, fit-to-corners) - drives the live
    // dashed preview from the last placed point to the cursor.
    if (traceActive || scaleCal || fitCorners) {
      const w = clientToWorld(evt);
      if (w) setTraceCursor({ x: w.x, y: w.y });
    }
    // Background pan takes precedence over deselect-on-click. The pan
    // starts only after the pointer has crossed the dead-zone - single
    // clicks on the background still deselect via onPointerUp.
    const pan = panRef.current;
    if (pan) {
      const dx = evt.clientX - pan.startX;
      const dy = evt.clientY - pan.startY;
      if (!pan.panning && dx * dx + dy * dy < 16) return;
      if (!pan.panning) {
        pan.panning = true;
        setIsPanning(true);
      }
      const svg = svgRef.current;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      // Convert pixel delta to world delta in the pan-start viewBox.
      const dxWorld = (dx / rect.width) * pan.startVB.w;
      const dyWorld = (dy / rect.height) * pan.startVB.h;
      setViewBox({
        x: pan.startVB.x - dxWorld,
        y: pan.startVB.y - dyWorld,
        w: pan.startVB.w,
        h: pan.startVB.h,
      });
      return;
    }
    const drag = dragRef.current;
    if (!drag) return;
    if (!drag.started) {
      const dx = evt.clientX - drag.startClientX;
      const dy = evt.clientY - drag.startClientY;
      if (dx * dx + dy * dy < 16) return; // 4 px threshold
      drag.started = true;
      onRoomDragStart?.(drag.id);
    }
    const world = clientToWorld(evt);
    if (!world) return;
    if (drag.kind === "move") {
      const x = snap(world.x + drag.offsetX, snapStep);
      const y = snap(world.y + drag.offsetY, snapStep);
      const fields = { x_m: x, y_m: y };
      // Polygon rooms: shift every vertex by the same delta so the shape
      // moves rigidly with the bbox. The bbox/shape stay in sync because
      // they're translated by the same vector.
      if (drag.shapeAtStart) {
        const dx = x - drag.startX;
        const dy = y - drag.startY;
        fields.shape = drag.shapeAtStart.map(([px, py]) => [px + dx, py + dy]);
      }
      onRoomDragMove?.(drag.id, fields);
      setDragInfo(`x ${x.toFixed(1)} · y ${y.toFixed(1)} m`);
    } else if (drag.kind === "resize") {
      const cursorX = snap(world.x, snapStep);
      const cursorY = snap(world.y, snapStep);
      const newX = Math.min(cursorX, drag.anchorX);
      const newY = Math.min(cursorY, drag.anchorY);
      const newW = Math.max(MIN_DIM_M, Math.abs(drag.anchorX - cursorX));
      const newH = Math.max(MIN_DIM_M, Math.abs(drag.anchorY - cursorY));
      onRoomDragMove?.(drag.id, {
        x_m: newX,
        y_m: newY,
        width_m: newW,
        height_m: newH,
      });
      setDragInfo(`${newW.toFixed(1)} × ${newH.toFixed(1)} m`);
    } else if (drag.kind === "edge") {
      // Single-axis resize. The other dimension + its origin stay locked
      // to the pre-drag snapshot so a small slip on one axis can't smear
      // into the other.
      if (drag.edgeKey === "E") {
        const cursorX = snap(world.x, snapStep);
        const newW = Math.max(MIN_DIM_M, cursorX - drag.keepX);
        onRoomDragMove?.(drag.id, { width_m: newW });
        setDragInfo(`width ${newW.toFixed(1)} m`);
      } else if (drag.edgeKey === "W") {
        const cursorX = snap(world.x, snapStep);
        const right = drag.anchorX; // x_m + width (locked)
        const newX = Math.min(cursorX, right - MIN_DIM_M);
        const newW = right - newX;
        onRoomDragMove?.(drag.id, { x_m: newX, width_m: newW });
        setDragInfo(`width ${newW.toFixed(1)} m`);
      } else if (drag.edgeKey === "S") {
        const cursorY = snap(world.y, snapStep);
        const newH = Math.max(MIN_DIM_M, cursorY - drag.keepY);
        onRoomDragMove?.(drag.id, { height_m: newH });
        setDragInfo(`height ${newH.toFixed(1)} m`);
      } else if (drag.edgeKey === "N") {
        const cursorY = snap(world.y, snapStep);
        const bot = drag.anchorY; // y_m + height (locked)
        const newY = Math.min(cursorY, bot - MIN_DIM_M);
        const newH = bot - newY;
        onRoomDragMove?.(drag.id, { y_m: newY, height_m: newH });
        setDragInfo(`height ${newH.toFixed(1)} m`);
      }
    }
  };

  const onPointerUp = (evt) => {
    const pan = panRef.current;
    if (pan) {
      if (pan.panning) setIsPanning(false);
      if (!pan.panning) {
        if (pan.fitCandidate && fitCorners) {
          // Fit-to-corners click - same loupe-refinement flow as scale
          // calibration: nothing commits until the operator accepts the
          // magnified position.
          const svg = svgRef.current;
          const ctm = svg?.getScreenCTM();
          if (ctm) {
            const pt = svg.createSVGPoint();
            pt.x = evt.clientX;
            pt.y = evt.clientY;
            const local = pt.matrixTransform(ctm.inverse());
            setLoupe({
              initialPos: [local.x, local.y],
              pos: [local.x, local.y],
              kind: "fit",
            });
          }
        } else if (pan.scaleCalCandidate && scaleCal) {
          // Scale-calibration click. NO snap - calibration precision is
          // the whole point, snapping would defeat it. The click is also
          // not committed directly: we open a pixel-precision loupe so
          // the operator can refine the position before locking it in.
          const svg = svgRef.current;
          const ctm = svg?.getScreenCTM();
          if (ctm) {
            const pt = svg.createSVGPoint();
            pt.x = evt.clientX;
            pt.y = evt.clientY;
            const local = pt.matrixTransform(ctm.inverse());
            setLoupe({
              initialPos: [local.x, local.y],
              pos: [local.x, local.y],
            });
          }
        } else if (pan.traceCandidate && traceActive) {
          // Vertex drop. Translate the pointer's pixel coords back to
          // world coords via the SVG's current CTM (accounting for zoom).
          const svg = svgRef.current;
          const ctm = svg?.getScreenCTM();
          if (ctm) {
            const pt = svg.createSVGPoint();
            pt.x = evt.clientX;
            pt.y = evt.clientY;
            const local = pt.matrixTransform(ctm.inverse());
            const vx = snap(local.x, snapStep);
            const vy = snap(local.y, snapStep);
            // Close the polygon if the click is near the first vertex.
            const first = traceVerts[0];
            const closeRadius = snapStep * 2;
            if (
              first &&
              traceVerts.length >= 3 &&
              Math.hypot(first[0] - vx, first[1] - vy) <= closeRadius
            ) {
              onTraceCommit?.(traceVerts);
            } else {
              setTraceVerts((v) => [...v, [vx, vy]]);
            }
          }
        } else {
          // Single click on empty space (not tracing) → deselect.
          onSelectRoom?.(null);
        }
      }
      panRef.current = null;
    }
    const drag = dragRef.current;
    if (drag?.started) onRoomDragEnd?.(drag.id);
    dragRef.current = null;
    setDragInfo(null);
  };

  // Double-click anywhere in the canvas while tracing → commit (if we have
  // at least a triangle). Saves a trip to the keyboard.
  const onDoubleClick = (evt) => {
    if (!traceActive) return;
    evt.preventDefault();
    if (traceVerts.length >= 3) onTraceCommit?.(traceVerts);
  };

  // Background pointer-down: starts a pan or a deselect click.
  // We DON'T gate this on target === svgRef any more - every pointer-down
  // on the SVG that wasn't stopped by a room/handle handler bubbles up here
  // and can begin a pan. That means dragging on the floor-plan image (the
  // most natural place to pan from once zoomed in) now works. Rooms still
  // win because their handlers call stopPropagation.
  const onBackgroundPointerDown = (evt) => {
    panRef.current = {
      startX: evt.clientX,
      startY: evt.clientY,
      startVB: viewBox,
      panning: false,
      traceCandidate: traceActive,
      scaleCalCandidate: Boolean(scaleCal),
      fitCandidate: Boolean(fitCorners),
    };
  };

  // Wheel = zoom. Anchored at the cursor's world position so the point
  // under the cursor stays still as the operator zooms in / out - same UX
  // as Leaflet, Google Maps, every CAD app.
  // Zoom step is ~10% per wheel tick (was 15%) - finer control, less
  // chance of overshooting past the area of interest.
  const ZOOM_IN_FACTOR = 0.9;
  const ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR;
  // Zoom-in limit: 0.5 m wide is enough for sub-cm precision at typical
  // screen sizes. Below that the SVG numerics start to feel quantised.
  const MIN_VBW_M = 0.5;
  // Zoom-out limit: fit view + 20% slack. There's no reason to zoom past
  // "I can see the whole floor plan with a little breathing room" - the
  // operator just loses their work in empty space.
  const MAX_VBW_M = fitViewBox.w * 1.2;
  // Wheel handler is attached via a non-passive DOM listener (via the
  // useEffect below) - React's onWheel is passive by default in modern
  // browsers, so preventDefault on the synthetic event doesn't reliably
  // block the page from scrolling underneath. The DOM listener with
  // { passive: false } does, and also blocks Ctrl-wheel from triggering
  // the browser's own pinch-zoom.
  //
  // Modifier map (CAD-style):
  //   (none)     → zoom 10 % per tick, anchored at cursor
  //   Ctrl/Cmd   → zoom 3 %  (fine - also blocks browser pinch-zoom)
  //   Shift      → horizontal pan
  //   Alt        → vertical pan
  const PAN_FRACTION = 0.15; // each wheel tick shifts viewBox by 15 % of its current size
  const onWheel = (evt) => {
    evt.preventDefault();
    const svg = svgRef.current;
    if (!svg) return;
    // Browser convention: on macOS Shift+wheel routes deltaY to deltaX, but
    // not on every browser/OS. Read whichever axis has the larger signal so
    // the gesture works the same everywhere.
    const rawDelta =
      Math.abs(evt.deltaX) > Math.abs(evt.deltaY) ? evt.deltaX : evt.deltaY;
    // Shift → horizontal pan.
    if (evt.shiftKey && !evt.ctrlKey && !evt.metaKey && !evt.altKey) {
      const dx = viewBox.w * PAN_FRACTION * Math.sign(rawDelta);
      setViewBox({ ...viewBox, x: viewBox.x + dx });
      return;
    }
    // Alt → vertical pan.
    if (evt.altKey && !evt.ctrlKey && !evt.metaKey && !evt.shiftKey) {
      const dy = viewBox.h * PAN_FRACTION * Math.sign(rawDelta);
      setViewBox({ ...viewBox, y: viewBox.y + dy });
      return;
    }
    // Otherwise: zoom anchored at the cursor.
    const rect = svg.getBoundingClientRect();
    const cx = viewBox.x + ((evt.clientX - rect.left) / rect.width) * viewBox.w;
    const cy = viewBox.y + ((evt.clientY - rect.top) / rect.height) * viewBox.h;
    let inFactor = ZOOM_IN_FACTOR;
    if (evt.ctrlKey || evt.metaKey) inFactor = 0.97; // fine zoom
    const outFactor = 1 / inFactor;
    const factor = evt.deltaY > 0 ? outFactor : inFactor;
    const newW = Math.max(MIN_VBW_M, Math.min(MAX_VBW_M, viewBox.w * factor));
    const newH = newW * (viewBox.h / viewBox.w);
    const newX = cx - ((cx - viewBox.x) / viewBox.w) * newW;
    const newY = cy - ((cy - viewBox.y) / viewBox.h) * newH;
    setViewBox({ x: newX, y: newY, w: newW, h: newH });
  };
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const handler = (e) => onWheel(e);
    svg.addEventListener("wheel", handler, { passive: false });
    return () => svg.removeEventListener("wheel", handler);
    // We re-bind whenever viewBox changes so the handler closes over the
    // latest value. (`onWheel` captures viewBox at definition time.)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewBox]);

  // Corner handle size in metres - visible at the typical floor-plan zoom.
  // 0.7 m radius for selected room corners - wide enough to grab on a touch
  // screen without obscuring the room outline at typical floor sizes.
  const HANDLE_R_M = 0.7;

  // World-north direction in the floor-plan's LOCAL frame. With our
  // clockwise-from-north azimuth convention, a world-north unit vector
  // (0, 1) in east/north maps back to (-sin(az), cos(az)) in local +x/+y.
  // Used to render a tiny compass needle in the corner so the operator
  // remembers the floor-plan view is the LOCAL frame, not the world frame
  // (the rotation lives entirely in section 1's calibration).
  const azDeg = Number(floorPlan?.georef?.azimuth_deg) || 0;
  const azRad = (azDeg * Math.PI) / 180;
  const northLocal = { x: -Math.sin(azRad), y: Math.cos(azRad) };

  // Cursor state for the canvas itself (rooms / handles override via their
  // own inline cursor styles).
  //   trace mode → crosshair
  //   pan active → grabbing
  //   else       → grab (signals: drag empty space to pan)
  const canvasCursor =
    traceActive || scaleCal || fitCorners
      ? "crosshair"
      : isPanning
      ? "grabbing"
      : "grab";

  return (
    <div
      style={{
        marginTop: 16,
        position: "relative",
        // Stop the operator's click-and-drag outside the SVG from selecting
        // the room label / dimension text as they release. The canvas isn't
        // a document - text inside the SVG is decoration, not content.
        userSelect: "none",
        WebkitUserSelect: "none",
      }}
    >
      {/* Frame badge: a constant reminder that section 2 is in the floor
          plan's LOCAL coordinate frame (image axis-aligned, as received),
          while section 1's calibration encodes the rotation to the world.
          Includes a small SVG compass needle pointing at world-north
          inside this local frame. */}
      <div
        style={{
          position: "absolute",
          // Drops below the editing pill when one is shown - both live in
          // the top-right corner and used to overlap.
          top: editingRoomId ? 46 : 10,
          right: 10,
          zIndex: 10,
          background: "rgba(8,14,32,0.92)",
          border: "1px solid rgba(255,255,255,0.10)",
          borderRadius: 6,
          padding: "6px 10px",
          color: "#cce0ff",
          fontFamily: "ui-monospace, monospace",
          fontSize: 10,
          pointerEvents: "none",
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}
        title={`Section 2 works in the floor plan's local frame (axis-aligned to the image as uploaded). World rotation = ${azDeg.toFixed(1)}°, set in section 1.`}
      >
        <svg width="22" height="22" viewBox="-1 -1 2 2" style={{ overflow: "visible" }}>
          <circle cx="0" cy="0" r="0.95" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="0.04" />
          <line
            x1="0"
            y1="0"
            x2={northLocal.x * 0.78}
            y2={-northLocal.y * 0.78}
            stroke="#ff6b78"
            strokeWidth="0.10"
            strokeLinecap="round"
          />
          <text
            x={northLocal.x * 0.78}
            y={-northLocal.y * 0.78 - 0.1}
            fill="#ff6b78"
            fontSize="0.45"
            fontFamily="ui-sans-serif"
            textAnchor="middle"
            dominantBaseline="alphabetic"
          >
            N
          </text>
        </svg>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
          <span style={{ color: "#7a8aab" }}>local frame</span>
          <span>world az {azDeg.toFixed(1)}°</span>
        </div>
      </div>
      {traceActive && (
        <div
          style={{
            position: "absolute",
            top: 10,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10,
            background: "rgba(8,14,32,0.95)",
            border: "1px solid #fbbf2488",
            borderRadius: 6,
            padding: "4px 12px",
            color: "#fbbf24",
            fontFamily: "ui-monospace, monospace",
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          ↪ trace · click vertices ({traceVerts.length})
          {" · "}
          {traceVerts.length >= 3
            ? "click first / Enter / dbl-click to close · Backspace = undo · Esc"
            : "need ≥ 3 vertices · Backspace = undo · Esc"}
        </div>
      )}

      {fitCorners && (
        <div
          style={{
            position: "absolute",
            top: 10,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10,
            background: "rgba(8,14,32,0.95)",
            border: "1px solid #38bdf888",
            borderRadius: 6,
            padding: "4px 12px",
            color: "#38bdf8",
            fontFamily: "ui-monospace, monospace",
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          ⌖ fit corners ·{" "}
          {fitCorners.p1
            ? "click the OPPOSITE corner of the room on the image · Esc = restart"
            : "click one corner of the room on the image (loupe refines) · Esc"}
        </div>
      )}

      {/* Edit-mode pill - present when a room is being actively edited.
          Same affordance as section 1's pill so the operator's mental
          model is consistent across sections. */}
      {editingRoomId && !traceActive && !scaleCal && !fitCorners && (
        <div
          style={{
            position: "absolute",
            top: 10,
            right: 10,
            zIndex: 10,
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "rgba(8,14,32,0.92)",
            border: "1px solid rgba(93,255,176,0.5)",
            borderRadius: 6,
            padding: "4px 10px",
            color: "#5dffb0",
            fontFamily: "ui-monospace, monospace",
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          <span>editing</span>
          <button
            type="button"
            onClick={() => onExitEdit?.()}
            title="Lock the room - back to view mode"
            style={{
              padding: "2px 8px",
              background: "rgba(93,255,176,0.18)",
              color: "#5dffb0",
              border: "1px solid #5dffb088",
              borderRadius: 4,
              fontSize: 10,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, monospace",
              cursor: "pointer",
            }}
          >
            ✓ done
          </button>
        </div>
      )}

      {/* Scale-calibration guided panel. Floats top-center; semi-translucent
          so the canvas underneath stays visible. Stays out of the bottom
          half of the canvas so the operator can click freely. */}
      {scaleCal && (() => {
        // Stage hint reflects the picker state machine.
        const stage = scaleCal.pendingP1 && scaleCal.pendingP2
          ? "type-distance"
          : scaleCal.pendingP1
          ? "pick-p2"
          : "pick-p1";
        // Per-ref scale + per-ref residual in metres (how far this ref's
        // implied scale differs from the mean, expressed as the metric
        // miss on the original click length).
        const refs = (scaleCal.refs || []).map((r) => ({
          ...r,
          scale: r.distNow > 0 ? r.knownM / r.distNow : null,
        }));
        const validScales = refs
          .map((r) => r.scale)
          .filter((s) => Number.isFinite(s) && s > 0);
        const sAvg = validScales.length > 0
          ? validScales.reduce((a, b) => a + b, 0) / validScales.length
          : null;
        let sStd = null;
        if (validScales.length >= 2 && sAvg != null) {
          sStd = Math.sqrt(
            validScales.reduce((a, b) => a + (b - sAvg) ** 2, 0) / validScales.length
          );
        }
        const cv = sStd != null && sAvg ? sStd / sAvg : null; // coefficient of variation
        // Confidence verdict: high < 1 %, medium < 5 %, low otherwise.
        // For 0/1 references there's no spread to measure → "unknown".
        let verdict = null;
        if (cv == null) verdict = { label: "-", color: "#7a8aab" };
        else if (cv < 0.01) verdict = { label: "high", color: "#5dffb0" };
        else if (cv < 0.05) verdict = { label: "medium", color: "#fbbf24" };
        else verdict = { label: "low - refs disagree", color: "#ff6b78" };
        const refsWithResidual = refs.map((r) => {
          if (sAvg == null || r.scale == null) return { ...r, residualM: null };
          // residual is "if I applied sAvg, this ref's clicked distance
          // would predict residualM metres of error vs its known distance".
          const predictedKnown = r.distNow * sAvg;
          return { ...r, residualM: predictedKnown - r.knownM };
        });
        return (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 20,
              minWidth: 360,
              maxWidth: 460,
              background: "rgba(8,14,32,0.96)",
              border: "1px solid rgba(56,189,248,0.45)",
              borderRadius: 8,
              padding: "10px 12px",
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              color: "#e6edf7",
              boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
            }}
          >
            {/* Header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 6,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  color: "#9ec3ff",
                  letterSpacing: "0.10em",
                  textTransform: "uppercase",
                }}
              >
                ↹ scale calibration · {refs.length} ref{refs.length === 1 ? "" : "s"}
              </div>
              <button
                type="button"
                onClick={() => setScaleCal(null)}
                title="Cancel calibration without applying"
                style={{
                  padding: "1px 6px",
                  background: "transparent",
                  color: "#7a8aab",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: 3,
                  fontSize: 10,
                  cursor: "pointer",
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                ✕
              </button>
            </div>

            {/* Stage hint */}
            <div
              style={{
                padding: "6px 8px",
                marginBottom: 8,
                background: "rgba(56,189,248,0.08)",
                border: "1px solid rgba(56,189,248,0.25)",
                borderRadius: 4,
                color: "#cce0ff",
                lineHeight: 1.4,
              }}
            >
              {stage === "pick-p1" && (
                <>
                  <span style={{ color: "#fbbf24" }}>● </span>
                  click the <strong>first point</strong> of a reference (a known
                  feature: wall, doorway, annotated dimension)
                </>
              )}
              {stage === "pick-p2" && (
                <>
                  <span style={{ color: "#fbbf24" }}>● </span>
                  click the <strong>second point</strong> - the other end of the
                  same feature
                </>
              )}
              {stage === "type-distance" && (
                <>
                  <span style={{ color: "#5dffb0" }}>● </span>
                  type the <strong>known distance</strong> between these two
                  points in metres
                </>
              )}
            </div>

            {/* Pending-pair distance entry. Auto-focused so the operator
                can type without a mouse trip. */}
            {stage === "type-distance" && (() => {
              const dist = Math.hypot(
                scaleCal.pendingP2[0] - scaleCal.pendingP1[0],
                scaleCal.pendingP2[1] - scaleCal.pendingP1[1]
              );
              return (
                <div
                  style={{
                    padding: "6px 8px",
                    marginBottom: 8,
                    background: "rgba(251,191,36,0.08)",
                    border: "1px solid rgba(251,191,36,0.3)",
                    borderRadius: 4,
                  }}
                >
                  <div
                    style={{
                      fontSize: 10,
                      color: "#fbbf24",
                      marginBottom: 4,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                    }}
                  >
                    pending · {dist.toFixed(2)} m in current scale
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <input
                      ref={(el) => el && stage === "type-distance" && el.focus()}
                      type="number"
                      step="0.01"
                      min="0.05"
                      placeholder="known m"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          const v = Number(e.currentTarget.value);
                          if (!(v > 0)) return;
                          setScaleCal({
                            ...scaleCal,
                            refs: [
                              ...(scaleCal.refs || []),
                              {
                                id: `ref-${Date.now().toString(36)}`,
                                p1: scaleCal.pendingP1,
                                p2: scaleCal.pendingP2,
                                distNow: dist,
                                knownM: v,
                              },
                            ],
                            pendingP1: null,
                            pendingP2: null,
                            picking: "p1",
                          });
                        } else if (e.key === "Escape") {
                          setScaleCal({
                            ...scaleCal,
                            pendingP1: null,
                            pendingP2: null,
                            picking: "p1",
                          });
                        }
                      }}
                      style={{
                        flex: 1,
                        padding: "4px 8px",
                        background: "rgba(255,255,255,0.04)",
                        border: "1px solid rgba(255,255,255,0.18)",
                        borderRadius: 3,
                        color: "#e6edf7",
                        fontFamily: "ui-monospace, monospace",
                        fontSize: 11,
                      }}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setScaleCal({
                          ...scaleCal,
                          pendingP1: null,
                          pendingP2: null,
                          picking: "p1",
                        })
                      }
                      style={{
                        padding: "4px 8px",
                        background: "transparent",
                        color: "#7a8aab",
                        border: "1px solid rgba(255,255,255,0.18)",
                        borderRadius: 3,
                        fontSize: 10,
                        cursor: "pointer",
                        fontFamily: "ui-monospace, monospace",
                      }}
                    >
                      discard
                    </button>
                  </div>
                  <div
                    style={{
                      fontSize: 9,
                      color: "#7a8aab",
                      marginTop: 4,
                    }}
                  >
                    Enter to commit · Esc to redo the pair
                  </div>
                </div>
              );
            })()}

            {/* References list */}
            {refsWithResidual.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                {refsWithResidual.map((r, i) => (
                  <div
                    key={r.id}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "auto 1fr auto",
                      gap: 6,
                      alignItems: "center",
                      padding: "3px 0",
                      borderBottom: "1px solid rgba(255,255,255,0.04)",
                      fontSize: 10,
                    }}
                  >
                    <span style={{ color: "#7a8aab" }}>#{i + 1}</span>
                    <span style={{ color: "#cce0ff" }}>
                      {r.knownM.toFixed(2)} m{" "}
                      <span style={{ color: "#7a8aab" }}>vs</span>{" "}
                      {r.distNow.toFixed(2)} m{" "}
                      <span style={{ color: "#9ec3ff" }}>
                        ×{r.scale ? r.scale.toFixed(4) : "-"}
                      </span>
                      {r.residualM != null && (
                        <span
                          style={{
                            color:
                              Math.abs(r.residualM) < 0.1
                                ? "#5dffb0"
                                : Math.abs(r.residualM) < 0.5
                                ? "#fbbf24"
                                : "#ff6b78",
                            marginLeft: 6,
                          }}
                        >
                          Δ{r.residualM >= 0 ? "+" : ""}{r.residualM.toFixed(2)} m
                        </span>
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setScaleCal({
                          ...scaleCal,
                          refs: scaleCal.refs.filter((rr) => rr.id !== r.id),
                        })
                      }
                      title="Remove this reference"
                      style={{
                        padding: "0 5px",
                        background: "transparent",
                        color: "#7a8aab",
                        border: "1px solid rgba(255,255,255,0.10)",
                        borderRadius: 3,
                        fontSize: 9,
                        cursor: "pointer",
                        fontFamily: "ui-monospace, monospace",
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Statistics + confidence */}
            {sAvg != null && (
              <div
                style={{
                  padding: "6px 8px",
                  marginBottom: 8,
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 4,
                  fontSize: 10,
                  lineHeight: 1.6,
                  color: "#cce0ff",
                }}
              >
                <div>
                  mean scale <strong>×{sAvg.toFixed(4)}</strong>
                </div>
                <div style={{ color: "#7a8aab" }}>
                  σ {sStd != null ? sStd.toFixed(4) : "-"}
                  {cv != null && <> · {(cv * 100).toFixed(2)}% relative</>}
                </div>
                <div style={{ color: verdict.color }}>
                  confidence: <strong>{verdict.label}</strong>
                  {cv != null && refs.length >= 2 && (
                    <>
                      {" "}
                      · expected residual ±{(cv * 100).toFixed(1)}% per metre
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Apply */}
            <button
              type="button"
              disabled={sAvg == null}
              onClick={() => onScaleCalApply?.(sAvg)}
              style={{
                width: "100%",
                padding: "6px 10px",
                background: sAvg != null ? "rgba(93,255,176,0.18)" : "transparent",
                color: sAvg != null ? "#5dffb0" : "#7a8aab",
                border: `1px solid ${sAvg != null ? "#5dffb088" : "rgba(255,255,255,0.12)"}`,
                borderRadius: 4,
                fontSize: 11,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                fontFamily: "ui-monospace, monospace",
                cursor: sAvg != null ? "pointer" : "not-allowed",
                opacity: sAvg != null ? 1 : 0.5,
              }}
            >
              ✓ apply (×{sAvg != null ? sAvg.toFixed(4) : "-"})
            </button>
          </div>
        );
      })()}

      {/* Pixel-precision loupe. Opens after every scale-calibration click
          so the operator can refine the position on a magnified view before
          committing. Fixed view (anchored at the rough click) - clicks
          inside the loupe move the crosshair to that location. */}
      {loupe && (() => {
        const LOUPE_PX = 320;
        const LOUPE_M = 4; // shows a 4 m × 4 m region around the click
        const half = LOUPE_M / 2;
        const vbX = loupe.initialPos[0] - half;
        const vbY = loupe.initialPos[1] - half;
        const loupeVB = `${vbX} ${vbY} ${LOUPE_M} ${LOUPE_M}`;
        const fpImg = floorPlan?.image?.data_url;
        // Distance the operator has moved the crosshair from the initial
        // click - surfaced in the caption so they can see how much they're
        // refining.
        const dx = loupe.pos[0] - loupe.initialPos[0];
        const dy = loupe.pos[1] - loupe.initialPos[1];
        const refineDist = Math.hypot(dx, dy);
        // Pointer-based picking inside the loupe. Supports BOTH click-to-
        // position and drag-to-position - pointer-down captures, pointer-
        // move while captured updates pos continuously (fluid drag), pointer-
        // up releases. A single click without drag still works the same way.
        const setPosFromEvent = (evt) => {
          const svg = loupeSvgRef.current;
          if (!svg) return;
          const ctm = svg.getScreenCTM();
          if (!ctm) return;
          const pt = svg.createSVGPoint();
          pt.x = evt.clientX;
          pt.y = evt.clientY;
          const local = pt.matrixTransform(ctm.inverse());
          setLoupe((cur) => (cur ? { ...cur, pos: [local.x, local.y] } : cur));
        };
        const onLoupePointerDown = (evt) => {
          evt.currentTarget.setPointerCapture?.(evt.pointerId);
          setPosFromEvent(evt);
        };
        const onLoupePointerMove = (evt) => {
          // The pointerId is captured only while the button is held - so
          // hasPointerCapture is a clean "am I dragging?" test.
          if (evt.currentTarget.hasPointerCapture?.(evt.pointerId)) {
            setPosFromEvent(evt);
          }
        };
        const onLoupePointerUp = (evt) => {
          evt.currentTarget.releasePointerCapture?.(evt.pointerId);
        };
        const onAccept = () => {
          if (loupe.kind === "fit") handleFitAccept(loupe.pos);
          else onScaleCalClick?.(loupe.pos);
          setLoupe(null);
        };
        return (
          <div
            style={{
              position: "fixed",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              zIndex: 100,
              background: "rgba(8,14,32,0.98)",
              border: "1px solid rgba(56,189,248,0.5)",
              borderRadius: 10,
              padding: 14,
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              color: "#e6edf7",
              boxShadow: "0 12px 32px rgba(0,0,0,0.6)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 8,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  color: "#9ec3ff",
                  letterSpacing: "0.10em",
                  textTransform: "uppercase",
                }}
              >
                ✦ refine point - click or drag
              </div>
              <div style={{ color: "#7a8aab", fontSize: 10 }}>
                ±{(half * 100).toFixed(0)} cm view
              </div>
            </div>
            <svg
              ref={loupeSvgRef}
              viewBox={loupeVB}
              preserveAspectRatio="xMidYMid meet"
              width={LOUPE_PX}
              height={LOUPE_PX}
              onPointerDown={onLoupePointerDown}
              onPointerMove={onLoupePointerMove}
              onPointerUp={onLoupePointerUp}
              onPointerCancel={onLoupePointerUp}
              style={{
                background: "#070b18",
                borderRadius: 6,
                border: "1px solid rgba(255,255,255,0.10)",
                cursor: "crosshair",
                display: "block",
                touchAction: "none",
              }}
            >
              {fpImg && (
                <image
                  href={fpImg}
                  x={0}
                  y={0}
                  width={W}
                  height={H}
                  opacity={floorPlan.image.opacity ?? 0.7}
                  // Must match the main canvas mapping exactly or the loupe
                  // would magnify a shifted picture.
                  preserveAspectRatio="xMinYMin meet"
                  style={{ pointerEvents: "none" }}
                />
              )}
              {/* Fine 10 cm grid for sub-metric precision. */}
              <g style={{ pointerEvents: "none" }} opacity={0.3}>
                {Array.from({ length: Math.ceil(LOUPE_M / 0.1) + 1 }, (_, i) => {
                  const xx = Math.floor(vbX / 0.1) * 0.1 + i * 0.1;
                  return (
                    <line
                      key={`gx${i}`}
                      x1={xx}
                      y1={vbY}
                      x2={xx}
                      y2={vbY + LOUPE_M}
                      stroke="#3a82ff"
                      strokeWidth="0.005"
                    />
                  );
                })}
                {Array.from({ length: Math.ceil(LOUPE_M / 0.1) + 1 }, (_, i) => {
                  const yy = Math.floor(vbY / 0.1) * 0.1 + i * 0.1;
                  return (
                    <line
                      key={`gy${i}`}
                      x1={vbX}
                      y1={yy}
                      x2={vbX + LOUPE_M}
                      y2={yy}
                      stroke="#3a82ff"
                      strokeWidth="0.005"
                    />
                  );
                })}
              </g>
              {/* 1 m brighter grid */}
              <g style={{ pointerEvents: "none" }} opacity={0.5}>
                {Array.from({ length: Math.ceil(LOUPE_M) + 1 }, (_, i) => {
                  const xx = Math.floor(vbX) + i;
                  return (
                    <line
                      key={`mx${i}`}
                      x1={xx}
                      y1={vbY}
                      x2={xx}
                      y2={vbY + LOUPE_M}
                      stroke="#3a82ff"
                      strokeWidth="0.015"
                    />
                  );
                })}
                {Array.from({ length: Math.ceil(LOUPE_M) + 1 }, (_, i) => {
                  const yy = Math.floor(vbY) + i;
                  return (
                    <line
                      key={`my${i}`}
                      x1={vbX}
                      y1={yy}
                      x2={vbX + LOUPE_M}
                      y2={yy}
                      stroke="#3a82ff"
                      strokeWidth="0.015"
                    />
                  );
                })}
              </g>
              {/* Initial rough-click mark (where the click landed before refinement). */}
              <circle
                cx={loupe.initialPos[0]}
                cy={loupe.initialPos[1]}
                r={0.05}
                fill="none"
                stroke="#7a8aab"
                strokeWidth="0.015"
                style={{ pointerEvents: "none" }}
              />
              {/* Crosshair at the currently-selected precise position. */}
              <g style={{ pointerEvents: "none" }}>
                <line
                  x1={loupe.pos[0] - half * 0.5}
                  y1={loupe.pos[1]}
                  x2={loupe.pos[0] + half * 0.5}
                  y2={loupe.pos[1]}
                  stroke="#fbbf24"
                  strokeWidth="0.025"
                />
                <line
                  x1={loupe.pos[0]}
                  y1={loupe.pos[1] - half * 0.5}
                  x2={loupe.pos[0]}
                  y2={loupe.pos[1] + half * 0.5}
                  stroke="#fbbf24"
                  strokeWidth="0.025"
                />
                <circle
                  cx={loupe.pos[0]}
                  cy={loupe.pos[1]}
                  r={0.04}
                  fill="#fbbf24"
                  stroke="#0c1428"
                  strokeWidth="0.012"
                />
              </g>
            </svg>
            <div
              style={{
                marginTop: 8,
                color: "#cce0ff",
                lineHeight: 1.5,
                fontSize: 10,
              }}
            >
              pos {loupe.pos[0].toFixed(3)}, {loupe.pos[1].toFixed(3)} m
              {refineDist > 0.001 && (
                <span style={{ color: "#7a8aab" }}> · refined {refineDist.toFixed(3)} m</span>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button
                type="button"
                onClick={onAccept}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  background: "rgba(93,255,176,0.18)",
                  color: "#5dffb0",
                  border: "1px solid #5dffb088",
                  borderRadius: 4,
                  fontSize: 11,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                }}
              >
                ✓ accept (Enter)
              </button>
              <button
                type="button"
                onClick={() => setLoupe(null)}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  background: "transparent",
                  color: "#9ec3ff",
                  border: "1px solid rgba(255,255,255,0.18)",
                  borderRadius: 4,
                  fontSize: 11,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                }}
              >
                ✕ cancel (Esc)
              </button>
            </div>
          </div>
        );
      })()}

      {dragInfo && (
        <div
          style={{
            position: "absolute",
            top: 10,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10,
            background: "rgba(8,14,32,0.95)",
            border: "1px solid rgba(255,255,255,0.18)",
            borderRadius: 6,
            padding: "4px 10px",
            color: "#e6edf7",
            fontFamily: "ui-monospace, monospace",
            fontSize: 11,
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {dragInfo}
        </div>
      )}

      {/* Zoom controls - bottom-left of the canvas. Wheel + drag-empty-space
          do the actual zooming/panning; these buttons are for discoverability
          and for the "I lost my view, take me back" case. */}
      <div
        style={{
          position: "absolute",
          bottom: 12,
          left: 12,
          zIndex: 10,
          display: "inline-flex",
          alignItems: "stretch",
          background: "rgba(8,14,32,0.92)",
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: 6,
          overflow: "hidden",
          fontFamily: "ui-monospace, monospace",
          fontSize: 11,
          color: "#cce0ff",
        }}
      >
        <button
          type="button"
          onClick={() => {
            const cx = viewBox.x + viewBox.w / 2;
            const cy = viewBox.y + viewBox.h / 2;
            const newW = Math.max(1, viewBox.w * ZOOM_IN_FACTOR);
            const newH = newW * (viewBox.h / viewBox.w);
            setViewBox({ x: cx - newW / 2, y: cy - newH / 2, w: newW, h: newH });
          }}
          title="Zoom in (or use the scroll wheel)"
          style={{
            padding: "4px 10px",
            background: "transparent",
            color: "#cce0ff",
            border: "none",
            cursor: "pointer",
            fontFamily: "ui-monospace, monospace",
          }}
        >
          +
        </button>
        <div style={{ width: 1, background: "rgba(255,255,255,0.10)" }} />
        <button
          type="button"
          onClick={() => {
            const cx = viewBox.x + viewBox.w / 2;
            const cy = viewBox.y + viewBox.h / 2;
            const newW = Math.min(MAX_VBW_M, viewBox.w * ZOOM_OUT_FACTOR);
            const newH = newW * (viewBox.h / viewBox.w);
            setViewBox({ x: cx - newW / 2, y: cy - newH / 2, w: newW, h: newH });
          }}
          title="Zoom out"
          style={{
            padding: "4px 10px",
            background: "transparent",
            color: "#cce0ff",
            border: "none",
            cursor: "pointer",
            fontFamily: "ui-monospace, monospace",
          }}
        >
          −
        </button>
        <div style={{ width: 1, background: "rgba(255,255,255,0.10)" }} />
        <button
          type="button"
          onClick={() => setViewBox(fitViewBox)}
          title="Fit the whole floor plan in the view"
          style={{
            padding: "4px 10px",
            background: "transparent",
            color: "#cce0ff",
            border: "none",
            cursor: "pointer",
            fontFamily: "ui-monospace, monospace",
          }}
        >
          ⛶ fit
        </button>
        <div style={{ width: 1, background: "rgba(255,255,255,0.10)" }} />
        <span
          style={{
            padding: "4px 10px",
            color: "#7a8aab",
            display: "inline-flex",
            alignItems: "center",
            fontVariantNumeric: "tabular-nums",
          }}
          title="Current zoom factor"
        >
          {zoomFactor.toFixed(zoomFactor >= 10 ? 0 : 1)}×
        </span>
      </div>
      <svg
        ref={svgRef}
        viewBox={vb}
        preserveAspectRatio="xMidYMid meet"
        width="100%"
        height="68vh"
        style={{
          background: "#070b18",
          borderRadius: 10,
          border: "1px solid rgba(58,130,255,0.2)",
          touchAction: "none",
          cursor: canvasCursor,
          // Block native browser drag (image ghost) on the floor-plan <image>.
          WebkitUserDrag: "none",
        }}
        onPointerDown={onBackgroundPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onDoubleClick={onDoubleClick}
        onDragStart={(e) => e.preventDefault()}
      >
        {/* Floor-plan extent + optional image background. The image keeps
            its native pixel aspect (uniform scale, anchored at the origin)
            instead of stretching to W×H: when the World-step calibration
            rescales the extent, the picture must scale the same amount on
            both axes or wall positions in this section would lie. */}
        {floorPlan?.image?.data_url ? (
          <image
            href={floorPlan.image.data_url}
            x={0}
            y={0}
            width={W}
            height={H}
            opacity={floorPlan.image.opacity ?? 0.7}
            preserveAspectRatio="xMinYMin meet"
          />
        ) : (
          <rect
            x={0}
            y={0}
            width={W}
            height={H}
            fill="rgba(58,130,255,0.04)"
            stroke="#3a82ff"
            strokeWidth="0.08"
            strokeDasharray="0.6 0.4"
          />
        )}
        <rect
          x={0}
          y={0}
          width={W}
          height={H}
          fill="none"
          stroke="#3a82ff"
          strokeWidth="0.06"
          strokeDasharray="0.4 0.2"
        />

        {/* Optional 1 m grid overlay - toggled from the global header. Lines
            spaced every 1 m in floor-plan-local metres, helps eyeballing
            distances between rooms without measuring. */}
        {showGrid && (
          <g style={{ pointerEvents: "none" }} opacity={0.35}>
            {Array.from({ length: Math.floor(W) + 1 }, (_, i) => (
              <line
                key={`gv${i}`}
                x1={i}
                y1={0}
                x2={i}
                y2={H}
                stroke="#3a82ff"
                strokeWidth="0.03"
              />
            ))}
            {Array.from({ length: Math.floor(H) + 1 }, (_, i) => (
              <line
                key={`gh${i}`}
                x1={0}
                y1={i}
                x2={W}
                y2={i}
                stroke="#3a82ff"
                strokeWidth="0.03"
              />
            ))}
          </g>
        )}

        {/* Unselected rooms first, so the selected room and its handles
            render on top. Polygon when room.shape is set, rectangle
            otherwise. Each room's <g> rotates around its centre by
            room.rotation_deg - for polygon rooms the centre is the bbox
            centre (still derived from x_m/y_m/width_m/height_m).
            HIDDEN during scale calibration - the operator is working on
            the floor plan itself, room rectangles are visual noise then. */}
        {!scaleCal && (rooms || []).filter((r) => r.id !== selectedRoomId).map((r) => {
          const rot = Number(r.rotation_deg) || 0;
          const cx = r.x_m + r.width_m / 2;
          const cy = r.y_m + r.height_m / 2;
          const hasShape = Array.isArray(r.shape) && r.shape.length >= 3;
          return (
            <g
              key={r.id}
              transform={`rotate(${rot} ${cx} ${cy})`}
              style={{ pointerEvents: traceActive ? "none" : undefined }}
            >
              {hasShape ? (
                <polygon
                  points={r.shape.map((p) => `${p[0]},${p[1]}`).join(" ")}
                  fill="rgba(255,179,71,0.10)"
                  stroke="#ffb347"
                  strokeWidth="0.16"
                  strokeLinejoin="round"
                  style={{ cursor: "pointer" }}
                  onPointerDown={(e) => onRoomPointerDown(e, r)}
                />
              ) : (
                <rect
                  x={r.x_m}
                  y={r.y_m}
                  width={r.width_m}
                  height={r.height_m}
                  fill="rgba(255,179,71,0.10)"
                  stroke="#ffb347"
                  strokeWidth="0.16"
                  style={{ cursor: "pointer" }}
                  onPointerDown={(e) => onRoomPointerDown(e, r)}
                />
              )}
              <text
                x={cx}
                y={cy}
                fontSize={Math.min(r.width_m, r.height_m) * 0.16}
                fill="#ffd089"
                textAnchor="middle"
                dominantBaseline="middle"
                fontFamily="ui-monospace, monospace"
                style={{ pointerEvents: "none" }}
              >
                {r.label || r.id}
              </text>
            </g>
          );
        })}

        {/* Selected room - high-contrast cyan, with corner handles (only
            when un-rotated) + live dimension labels. Same colour scheme as
            the World step's edit mode so the visual language is consistent
            across sections. */}
        {!scaleCal && (rooms || []).filter((r) => r.id === selectedRoomId).map((r) => {
          const rot = Number(r.rotation_deg) || 0;
          const cx = r.x_m + r.width_m / 2;
          const cy = r.y_m + r.height_m / 2;
          const hasShape = Array.isArray(r.shape) && r.shape.length >= 3;
          const isEditing = editingRoomId === r.id;
          // Corner / edge handles render only when the room is in edit
          // mode, axis-aligned, rectangular (not polygon), and no other
          // canvas tool is intercepting clicks.
          const resizable =
            isEditing && !hasShape && Math.abs(rot) < 0.01 && !traceActive;
          return (
            <g
              key={r.id}
              transform={`rotate(${rot} ${cx} ${cy})`}
              style={{ pointerEvents: traceActive ? "none" : undefined }}
            >
              {hasShape ? (
                <polygon
                  points={r.shape.map((p) => `${p[0]},${p[1]}`).join(" ")}
                  fill="rgba(56,189,248,0.18)"
                  stroke="#38bdf8"
                  strokeWidth="0.22"
                  strokeLinejoin="round"
                  style={{ cursor: isEditing ? "grab" : "pointer" }}
                  onPointerDown={(e) => onRoomPointerDown(e, r)}
                />
              ) : (
                <rect
                  x={r.x_m}
                  y={r.y_m}
                  width={r.width_m}
                  height={r.height_m}
                  fill="rgba(56,189,248,0.18)"
                  stroke="#38bdf8"
                  strokeWidth="0.22"
                  style={{ cursor: isEditing ? "grab" : "pointer" }}
                  onPointerDown={(e) => onRoomPointerDown(e, r)}
                />
              )}
              <text
                x={cx}
                y={cy}
                fontSize={Math.min(r.width_m, r.height_m) * 0.18}
                fill="#cce0ff"
                textAnchor="middle"
                dominantBaseline="middle"
                fontFamily="ui-monospace, monospace"
                style={{ pointerEvents: "none" }}
              >
                {r.label || r.id}
              </text>
              {/* Width label on top edge */}
              <text
                x={cx}
                y={r.y_m - Math.max(0.4, r.width_m * 0.02)}
                fontSize={Math.max(0.8, Math.min(r.width_m, r.height_m) * 0.09)}
                fill="#9ec3ff"
                textAnchor="middle"
                fontFamily="ui-monospace, monospace"
                style={{ pointerEvents: "none" }}
              >
                {r.width_m.toFixed(1)} m
              </text>
              {/* Height label on right edge, rotated -90° to read along it */}
              <text
                x={r.x_m + r.width_m + Math.max(0.4, r.height_m * 0.02)}
                y={cy}
                fontSize={Math.max(0.8, Math.min(r.width_m, r.height_m) * 0.09)}
                fill="#9ec3ff"
                textAnchor="middle"
                fontFamily="ui-monospace, monospace"
                style={{ pointerEvents: "none" }}
                transform={`rotate(-90 ${r.x_m + r.width_m + Math.max(0.4, r.height_m * 0.02)} ${cy})`}
              >
                {r.height_m.toFixed(1)} m
              </text>
              {/* 4 edge midpoint handles - single-axis resize. Drawn under
                  the corner handles so corners take precedence when close
                  together. Each edge has its own resize cursor so the
                  operator can tell at a glance which axis will move. */}
              {resizable &&
                [
                  { key: "N", x: r.x_m + r.width_m / 2, y: r.y_m,                  cursor: "ns-resize" },
                  { key: "S", x: r.x_m + r.width_m / 2, y: r.y_m + r.height_m,     cursor: "ns-resize" },
                  { key: "W", x: r.x_m,                  y: r.y_m + r.height_m / 2, cursor: "ew-resize" },
                  { key: "E", x: r.x_m + r.width_m,      y: r.y_m + r.height_m / 2, cursor: "ew-resize" },
                ].map((e) => (
                  <circle
                    key={`edge-${e.key}`}
                    cx={e.x}
                    cy={e.y}
                    r={HANDLE_R_M * 0.85}
                    fill="#38bdf8"
                    stroke="#0c1428"
                    strokeWidth="0.12"
                    style={{ cursor: e.cursor }}
                    onPointerDown={(ev) => onEdgePointerDown(ev, r, e.key)}
                  />
                ))}
              {/* 4 corner resize handles - only shown when un-rotated. */}
              {resizable &&
                [
                  { key: "TL", x: r.x_m, y: r.y_m },
                  { key: "TR", x: r.x_m + r.width_m, y: r.y_m },
                  { key: "BL", x: r.x_m, y: r.y_m + r.height_m },
                  { key: "BR", x: r.x_m + r.width_m, y: r.y_m + r.height_m },
                ].map((c) => (
                  <circle
                    key={c.key}
                    cx={c.x}
                    cy={c.y}
                    r={HANDLE_R_M}
                    fill="#fbbf24"
                    stroke="#0c1428"
                    strokeWidth="0.12"
                    style={{ cursor: "nwse-resize" }}
                    onPointerDown={(e) => onCornerPointerDown(e, r, c.key)}
                  />
                ))}
            </g>
          );
        })}

        {/* Trace overlay - drawn last so it sits above every room. Shows
            the in-progress polygon vertices + a live dashed line from the
            last vertex to the cursor. Clicking the first vertex (within
            2× the snap step) closes the polygon. */}
        {traceActive && (
          <g style={{ pointerEvents: "none" }}>
            {traceVerts.length >= 2 && (
              <polyline
                points={traceVerts.map((p) => `${p[0]},${p[1]}`).join(" ")}
                fill="none"
                stroke="#fbbf24"
                strokeWidth="0.18"
                strokeLinejoin="round"
              />
            )}
            {traceVerts.length >= 3 && traceCursor && (
              <polyline
                points={`${traceVerts[traceVerts.length - 1][0]},${
                  traceVerts[traceVerts.length - 1][1]
                } ${traceCursor.x},${traceCursor.y} ${traceVerts[0][0]},${traceVerts[0][1]}`}
                fill="none"
                stroke="#fbbf24"
                strokeWidth="0.10"
                strokeDasharray="0.6 0.4"
                opacity="0.6"
              />
            )}
            {traceVerts.length === 1 && traceCursor && (
              <line
                x1={traceVerts[0][0]}
                y1={traceVerts[0][1]}
                x2={traceCursor.x}
                y2={traceCursor.y}
                stroke="#fbbf24"
                strokeWidth="0.12"
                strokeDasharray="0.6 0.4"
                opacity="0.7"
              />
            )}
            {traceVerts.length >= 2 && traceCursor && (
              <line
                x1={traceVerts[traceVerts.length - 1][0]}
                y1={traceVerts[traceVerts.length - 1][1]}
                x2={traceCursor.x}
                y2={traceCursor.y}
                stroke="#fbbf24"
                strokeWidth="0.12"
                strokeDasharray="0.6 0.4"
                opacity="0.7"
              />
            )}
            {traceVerts.map((p, i) => (
              <circle
                key={`tv${i}`}
                cx={p[0]}
                cy={p[1]}
                r={0.4}
                fill="#fbbf24"
                stroke="#0c1428"
                strokeWidth="0.08"
              />
            ))}
          </g>
        )}

        {/* Scale-calibration overlay - confirmed refs as green segments
            with their known-vs-current label, plus the pending pair (one or
            two yellow points) for the in-progress reference. */}
        {scaleCal && (
          <g style={{ pointerEvents: "none" }}>
            {(scaleCal.refs || []).map((r, i) => {
              const midX = (r.p1[0] + r.p2[0]) / 2;
              const midY = (r.p1[1] + r.p2[1]) / 2;
              const labelSize = Math.max(0.6, viewBox.w * 0.012);
              return (
                <g key={r.id}>
                  <line
                    x1={r.p1[0]}
                    y1={r.p1[1]}
                    x2={r.p2[0]}
                    y2={r.p2[1]}
                    stroke="#5dffb0"
                    strokeWidth="0.15"
                    opacity="0.9"
                  />
                  <circle cx={r.p1[0]} cy={r.p1[1]} r={0.35} fill="#5dffb0" stroke="#0c1428" strokeWidth="0.08" />
                  <circle cx={r.p2[0]} cy={r.p2[1]} r={0.35} fill="#5dffb0" stroke="#0c1428" strokeWidth="0.08" />
                  <text
                    x={midX}
                    y={midY - labelSize * 0.4}
                    fontSize={labelSize}
                    fill="#aaffd6"
                    textAnchor="middle"
                    fontFamily="ui-monospace, monospace"
                  >
                    #{i + 1} · {r.knownM.toFixed(2)} m
                  </text>
                </g>
              );
            })}
            {/* pendingP1 (already committed via loupe-accept). */}
            {scaleCal.pendingP1 && (
              <circle
                cx={scaleCal.pendingP1[0]}
                cy={scaleCal.pendingP1[1]}
                r={0.4}
                fill="#fbbf24"
                stroke="#0c1428"
                strokeWidth="0.08"
              />
            )}
            {/* Both points committed: solid yellow segment. */}
            {scaleCal.pendingP1 && scaleCal.pendingP2 && (
              <>
                <line
                  x1={scaleCal.pendingP1[0]}
                  y1={scaleCal.pendingP1[1]}
                  x2={scaleCal.pendingP2[0]}
                  y2={scaleCal.pendingP2[1]}
                  stroke="#fbbf24"
                  strokeWidth="0.15"
                />
                <circle
                  cx={scaleCal.pendingP2[0]}
                  cy={scaleCal.pendingP2[1]}
                  r={0.4}
                  fill="#fbbf24"
                  stroke="#0c1428"
                  strokeWidth="0.08"
                />
              </>
            )}
            {/* While the precision loupe is open, FREEZE the canvas under
                it: the rough click renders as a static yellow dot, and any
                in-progress segment becomes solid (not cursor-following).
                Cursor-following is reserved for the no-loupe state below. */}
            {loupe && !scaleCal.pendingP2 && (
              <circle
                cx={loupe.initialPos[0]}
                cy={loupe.initialPos[1]}
                r={0.4}
                fill="#fbbf24"
                stroke="#0c1428"
                strokeWidth="0.08"
                opacity={0.7}
              />
            )}
            {loupe && scaleCal.pendingP1 && !scaleCal.pendingP2 && (
              <line
                x1={scaleCal.pendingP1[0]}
                y1={scaleCal.pendingP1[1]}
                x2={loupe.initialPos[0]}
                y2={loupe.initialPos[1]}
                stroke="#fbbf24"
                strokeWidth="0.15"
                opacity={0.7}
              />
            )}
            {/* Live cursor preview - ONLY when the loupe is closed. */}
            {!loupe && scaleCal.pendingP1 && !scaleCal.pendingP2 && traceCursor && (
              <line
                x1={scaleCal.pendingP1[0]}
                y1={scaleCal.pendingP1[1]}
                x2={traceCursor.x}
                y2={traceCursor.y}
                stroke="#fbbf24"
                strokeWidth="0.10"
                strokeDasharray="0.6 0.4"
                opacity="0.7"
              />
            )}
          </g>
        )}

        {/* Fit-to-corners markers: confirmed corner 1 + live preview
            rectangle from corner 1 to the cursor (or to the loupe pick). */}
        {fitCorners && (
          <g style={{ pointerEvents: "none" }}>
            {fitCorners.p1 && (
              <circle
                cx={fitCorners.p1[0]}
                cy={fitCorners.p1[1]}
                r={0.35}
                fill="#38bdf8"
                stroke="#0c1428"
                strokeWidth="0.08"
              />
            )}
            {fitCorners.p1 && (loupe?.pos || traceCursor) && (() => {
              const tgt = loupe?.pos || [traceCursor.x, traceCursor.y];
              const x = Math.min(fitCorners.p1[0], tgt[0]);
              const y = Math.min(fitCorners.p1[1], tgt[1]);
              const w = Math.abs(tgt[0] - fitCorners.p1[0]);
              const h = Math.abs(tgt[1] - fitCorners.p1[1]);
              return (
                <>
                  <rect
                    x={x} y={y} width={w} height={h}
                    fill="rgba(56,189,248,0.08)"
                    stroke="#38bdf8"
                    strokeWidth="0.1"
                    strokeDasharray="0.5 0.3"
                  />
                  <text
                    x={x + w / 2}
                    y={y - 0.4}
                    textAnchor="middle"
                    fill="#38bdf8"
                    fontSize="0.9"
                    fontFamily="ui-monospace, monospace"
                  >
                    {w.toFixed(2)} × {h.toFixed(2)} m
                  </text>
                </>
              );
            })()}
            {loupe?.kind === "fit" && (
              <circle
                cx={loupe.initialPos[0]}
                cy={loupe.initialPos[1]}
                r={0.35}
                fill="#38bdf8"
                stroke="#0c1428"
                strokeWidth="0.08"
                opacity={0.7}
              />
            )}
          </g>
        )}
      </svg>
    </div>
  );
}
