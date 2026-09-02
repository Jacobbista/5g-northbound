import { useEffect, useMemo, useRef, useState } from "react";
import {
  Edges,
  Grid,
  Html,
  Line,
  OrbitControls,
  Stars,
} from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { CAMARA_API_BASE, FLOOR_D, FLOOR_W, GPS_ORIGIN_LAT, GPS_ORIGIN_LON } from "../config";
import { ema2d } from "../lib/smoothing";
import { shortLabel } from "../lib/label";

// Scene labels sit below the UI chrome (detail panel, header). Cap the drei
// Html z-index so a floating label never covers an open panel.
const LABEL_Z = [30, 0];

const M_PER_DEG = 111320;

// Per-technology visual palette. Anchors with unknown technology fall back to
// the wifi entry. Mirrors the registry on the placement-editor side.
//
// `fiveg` and `gnss` are display-only here - no measurement adapter exists
// for those sources. See docs/adapters.md#status-by-technology.
const TECH_PALETTE = {
  wifi:   { primary: "#ffb347", glow: "#ff8c00", text: "#ffd089", label: "WiFi" },
  wittra: { primary: "#5dffb0", glow: "#16a085", text: "#aaffd6", label: "UWB"  },
  fiveg:  { primary: "#c084fc", glow: "#7c3aed", text: "#dbc1ff", label: "5G"   },
  gnss:   { primary: "#fbbf24", glow: "#b45309", text: "#fde68a", label: "GNSS" },
};
export const TECH_KEYS = ["wifi", "wittra", "fiveg", "gnss"];
// Muted palette for anchors that are not relevant to the focused asset: they
// recede so the contributing anchors read as the active set.
const DIM_PALETTE = { primary: "#3f4a5e", glow: "#2a3346", text: "#5a6987", label: "" };
const techOfAnchor = (a) => (a && a.technology) || "wifi";
const techPalette = (a) => TECH_PALETTE[techOfAnchor(a)] || TECH_PALETTE.wifi;
const TRAIL_MAX = 60;
const MARGIN = 6;
const STALE_MS = 10000;
// Display threshold for the reported fix accuracy (metres). Matches the
// sidebar's `imprecise` state in App.jsx; override per deployment via
// runtime env.
const ACCURACY_MAX_M = Number(
  (typeof window !== "undefined" && window.__ENV__?.VITE_ACCURACY_MAX_M) || 15
);
const DEFAULT_WALL_HEIGHT = 2.7;
const DEFAULT_OPENING_HEIGHT = 2.1;
const DEFAULT_WALL_THICK = 0.2;
// EMA weight: 0=no update, 1=no smoothing. ~0.35 absorbs ~3 samples worth of jitter.
const EMA_ALPHA = 0.35;

// Project a CAMARA fix (lat, lon) into THE canonical room frame the anchors use:
// room-local metres, origin top-left, x right, y down (canvas-y). This is the
// frame the placement editor stores and the engine speaks; the demo renders 3D
// z = canvas-y directly (no mirror). gpsToFloorPlanLocal yields georef-frame y
// (lower-left origin, north-up), so convert once: canvas-y = fpH - yFp, then
// subtract the room base. Uses the blueprint georef, NOT the legacy env
// GPS_ORIGIN (which pinned the demo to the wrong venue, throwing devices a
// million metres off-scene).
function toLocal(center, frame) {
  if (!center) return null;
  if (frame?.georef) {
    const { lat0, lon0, az, roomX, roomY, fpH } = frame;
    const mLat = M_PER_DEG;
    const mLon = M_PER_DEG * Math.cos((lat0 * Math.PI) / 180);
    const east = (center.longitude - lon0) * mLon;
    const north = (center.latitude - lat0) * mLat;
    const xFp = east * Math.cos(az) - north * Math.sin(az);
    const yFp = east * Math.sin(az) + north * Math.cos(az);
    const x = xFp - roomX;
    const z = (fpH - yFp) - roomY;
    return { x, z };
  }
  // Legacy fallback (no blueprint georef available).
  const x =
    (center.longitude - GPS_ORIGIN_LON) * M_PER_DEG * Math.cos((GPS_ORIGIN_LAT * Math.PI) / 180);
  const z = (center.latitude - GPS_ORIGIN_LAT) * M_PER_DEG;
  return { x, z };
}

const labelStyle = {
  padding: "3px 8px",
  borderRadius: 6,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 11,
  whiteSpace: "nowrap",
  transform: "translateY(-50%)",
  pointerEvents: "none",
  userSelect: "none",
  WebkitUserSelect: "none",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  backdropFilter: "blur(4px)",
};

function DeviceMarker({ x, z, radius, label, color, stale, hidden = false, onClick }) {
  const groupRef = useRef();
  const ring = useRef();
  const glow = useRef();
  const bodyRef = useRef();
  const renderColor = stale ? "#5a6470" : color;

  // Seed position + visibility scale once so a marker that starts hidden begins
  // at scale 0 and one that starts shown does not lerp in from the origin.
  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.set(x, 0, z);
      groupRef.current.scale.setScalar(hidden ? 0 : 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFrame(({ clock }, delta) => {
    const dt = Math.min(delta || 0.05, 0.1);
    const g = groupRef.current;
    if (g) {
      // Glide toward the latest fix (updates land every ~1-2s) so motion reads
      // as continuous, not a teleport per update.
      g.position.x += (x - g.position.x) * Math.min(1, dt * 1.8);
      g.position.z += (z - g.position.z) * Math.min(1, dt * 1.8);
      // Show / hide: eased scale in and out on the visibility toggle.
      const s = g.scale.x + ((hidden ? 0 : 1) - g.scale.x) * Math.min(1, dt * 8);
      g.scale.setScalar(s < 0.001 ? 0 : s);
    }
    const t = clock.getElapsedTime();
    if (bodyRef.current) {
      bodyRef.current.position.y = 0.6 + Math.sin(t * 2) * 0.06;
      bodyRef.current.rotation.y = t * 0.4;
    }
    if (ring.current) {
      if (stale) {
        ring.current.material.opacity = 0;
      } else {
        const p = (t % 1.6) / 1.6;
        ring.current.scale.setScalar(1 + p * 1.8);
        ring.current.material.opacity = 0.65 * (1 - p);
      }
    }
    if (glow.current && !stale) {
      glow.current.material.opacity = 0.35 + Math.sin(t * 3) * 0.12;
    }
  });

  return (
    // No `position` prop: binding it would re-apply [x,0,z] on every re-render
    // (~1/s) and snap the marker to the waypoint, defeating the per-frame lerp.
    // The group is positioned once in the effect above, then only by useFrame.
    <group ref={groupRef}>
      {/* Generous invisible hitbox: the small body is otherwise hard to hit, and
          a miss falls through to the canvas' onPointerMissed (which deselects),
          so the asset detail would never open. This is the single event target. */}
      <mesh
        position={[0, 1.0, 0]}
        onPointerDown={(e) => {
          if (hidden || !onClick) return;
          e.stopPropagation();
          onClick();
        }}
        onPointerOver={(e) => {
          if (hidden) return;
          e.stopPropagation();
          if (onClick) document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          if (onClick) document.body.style.cursor = "auto";
        }}
      >
        <cylinderGeometry args={[0.95, 0.95, 2.6, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {radius > 0 && !stale && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]} raycast={() => null}>
          <circleGeometry args={[radius, 64]} />
          <meshBasicMaterial color={renderColor} transparent opacity={0.08} />
        </mesh>
      )}
      {radius > 0 && !stale && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]} raycast={() => null}>
          <ringGeometry args={[radius - 0.08, radius, 64]} />
          <meshBasicMaterial color={renderColor} transparent opacity={0.55} />
        </mesh>
      )}

      <mesh ref={glow} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]} raycast={() => null}>
        <circleGeometry args={[0.85, 48]} />
        <meshBasicMaterial color={renderColor} transparent opacity={0.4} />
      </mesh>

      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.07, 0]} raycast={() => null}>
        <ringGeometry args={[0.55, 0.78, 48]} />
        <meshBasicMaterial color={renderColor} transparent opacity={0.7} />
      </mesh>

      <group ref={bodyRef}>
        <mesh raycast={() => null}>
          <octahedronGeometry args={[0.45, 0]} />
          <meshStandardMaterial
            color={renderColor}
            emissive={renderColor}
            emissiveIntensity={stale ? 0 : 1.2}
            metalness={0.4}
            roughness={0.25}
          />
        </mesh>
        <mesh scale={1.6} raycast={() => null}>
          <octahedronGeometry args={[0.45, 0]} />
          <meshBasicMaterial color={renderColor} transparent opacity={stale ? 0 : 0.12} />
        </mesh>
      </group>

      <mesh position={[0, 0.01, 0]} raycast={() => null}>
        <cylinderGeometry args={[0.08, 0.08, 1.4, 16]} />
        <meshBasicMaterial color={renderColor} transparent opacity={stale ? 0 : 0.18} />
      </mesh>

      <Html position={[0, 1.9, 0]} center distanceFactor={18} zIndexRange={LABEL_Z} pointerEvents="none" wrapperClass="scene-label">
        <div
          style={{
            ...labelStyle,
            pointerEvents: "none",
            background: stale ? "rgba(40,46,55,0.85)" : `${renderColor}cc`,
            color: "#fff",
            border: `1px solid ${renderColor}`,
            boxShadow: stale ? "none" : `0 0 12px ${renderColor}80`,
          }}
        >
          {label}
          {stale ? " · stale" : ""}
        </div>
      </Html>
    </group>
  );
}

function ApMarker({ id, x, z, height = 1.2, ceiling = DEFAULT_WALL_HEIGHT, hidden = false, colors = TECH_PALETTE.wifi, onClick }) {
  const groupRef = useRef();
  const ringRef = useRef();
  const pulseRef = useRef();
  const pulseTRef = useRef(0);
  const [hovered, setHovered] = useState(false);
  // Seed the visibility scale once so a layer that starts hidden begins at 0
  // and never flashes before the first frame.
  useEffect(() => {
    if (groupRef.current) groupRef.current.scale.setScalar(hidden ? 0 : 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.1); // clamp big gaps (demand frameloop)
    // Visibility scale: eased toward 0 (hidden) or 1 (shown) so a layer toggle
    // animates the anchor out / in instead of popping.
    if (groupRef.current) {
      const s = groupRef.current.scale.x;
      const ns = s + ((hidden ? 0 : 1) - s) * Math.min(1, dt * 8);
      groupRef.current.scale.setScalar(ns < 0.001 ? 0 : ns);
    }
    // Base ground ring brightens on hover.
    if (ringRef.current) {
      const target = hovered ? 0.55 : 0.16;
      const m = ringRef.current.material;
      m.opacity += (target - m.opacity) * Math.min(1, dt * 6);
    }
    // Ranging ping: a ring sweeps outward ONLY while hovered - reads as the
    // beacon actively measuring range, not a constant idle animation.
    if (pulseRef.current) {
      const m = pulseRef.current.material;
      if (hovered) {
        pulseTRef.current = (pulseTRef.current + dt * 0.7) % 1;
        pulseRef.current.scale.setScalar(1 + pulseTRef.current * 2.8);
        m.opacity = 0.5 * (1 - pulseTRef.current);
      } else {
        m.opacity += (0 - m.opacity) * Math.min(1, dt * 6);
      }
    }
  });
  // Above 85% of ceiling height = ceiling-mounted: render as a flat puck
  // tucked just below the ceiling with a faint drop ring on the floor.
  // Below = pole-style fixture (lab tripod, wall-mounted anchor).
  const isCeilingMounted = height >= ceiling * 0.85;
  const labelY = isCeilingMounted ? ceiling - 0.1 : height + 0.45;
  // The hitbox rises from the floor to just above the label and is wide, so the
  // whole natural target - fixture, column, and the area right under the label -
  // is clickable/hoverable with no dead gap between the 3D body and the label.
  const hitH = labelY + 0.6;
  return (
    <group ref={groupRef} position={[x, 0, z]}>
      {/* Invisible hitbox: the whole column is clickable and hoverable, not
          just the small head. Opacity 0 still receives the raycast; it is the
          single event target so overlapping decorative meshes never double-fire. */}
      <mesh
        position={[0, hitH / 2, 0]}
        onPointerDown={(e) => {
          if (hidden || !onClick) return;
          e.stopPropagation();
          onClick();
        }}
        onPointerOver={(e) => {
          if (hidden) return;
          e.stopPropagation();
          if (onClick) document.body.style.cursor = "pointer";
          setHovered(true);
        }}
        onPointerOut={() => {
          if (onClick) document.body.style.cursor = "auto";
          setHovered(false);
        }}
      >
        <cylinderGeometry args={[0.95, 0.95, hitH, 12]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Beacon footprint: concentric coverage rings on the floor - a static
          "positioning range" motif that reads as an anchor, not a spinner. */}
      <mesh ref={ringRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]}>
        <ringGeometry args={[0.42, 0.56, 48]} />
        <meshBasicMaterial color={colors.primary} transparent opacity={0.16} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]} raycast={() => null}>
        <ringGeometry args={[1.0, 1.05, 56]} />
        <meshBasicMaterial color={colors.primary} transparent opacity={0.09} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]} raycast={() => null}>
        <ringGeometry args={[1.6, 1.64, 64]} />
        <meshBasicMaterial color={colors.primary} transparent opacity={0.05} />
      </mesh>

      {/* Ranging ping: expands out of the anchor on hover only (see useFrame). */}
      <mesh ref={pulseRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]} raycast={() => null}>
        <ringGeometry args={[0.4, 0.5, 48]} />
        <meshBasicMaterial color={colors.primary} transparent opacity={0} />
      </mesh>

      {isCeilingMounted ? (
        <>
          {/* Drop-line from ceiling to floor - visual cue for the AP's
              projection. Not clickable: pointer events go through to the
              puck below it. */}
          <mesh position={[0, height / 2, 0]} raycast={() => null}>
            <cylinderGeometry args={[0.015, 0.015, height, 8]} />
            <meshBasicMaterial color={colors.primary} transparent opacity={0.25} />
          </mesh>
          {/* Puck - the AP's head. Clickable. Radius big enough to land a
              pointer on it without precision. */}
          <mesh position={[0, height - 0.1, 0]}>
            <cylinderGeometry args={[0.5, 0.5, 0.2, 32]} />
            <meshStandardMaterial
              color={colors.primary}
              emissive={colors.glow}
              emissiveIntensity={0.6}
              metalness={0.6}
              roughness={0.3}
            />
            <Edges color={colors.text} />
          </mesh>
          {/* Status dome on the puck face pointing down. Not clickable -
              the puck under it already captures the click. */}
          <mesh position={[0, height - 0.24, 0]} raycast={() => null}>
            <sphereGeometry args={[0.14, 16, 16]} />
            <meshStandardMaterial color={colors.text} emissive={colors.primary} emissiveIntensity={2} />
          </mesh>
        </>
      ) : (
        <>
          <mesh position={[0, height / 2, 0]}>
            <cylinderGeometry args={[0.18, 0.28, height, 16]} />
            <meshStandardMaterial
              color={colors.primary}
              emissive={colors.glow}
              emissiveIntensity={0.6}
              metalness={0.6}
              roughness={0.3}
            />
            <Edges color={colors.text} />
          </mesh>
          <mesh position={[0, height + 0.05, 0]}>
            <sphereGeometry args={[0.12, 16, 16]} />
            <meshStandardMaterial color={colors.text} emissive={colors.primary} emissiveIntensity={2} />
          </mesh>
        </>
      )}

      <Html position={[0, labelY, 0]} center distanceFactor={20} zIndexRange={LABEL_Z} pointerEvents="none" wrapperClass="scene-label">
        {/* The -50% lift lives on the WRAPPER (not the label), so the floating
            hint anchored to it sits truly above the VISUAL label, not below.
            Pointer-events off: the 3D hitbox owns all hover/click. */}
        <div style={{ position: "relative", transform: "translateY(-50%)", pointerEvents: "none" }}>
          {/* Hover cue: a tooltip that floats above the label with a caret,
              reading as an intentional "inspect" affordance. Never resizes the
              label (which would shift the scene). */}
          <div
            style={{
              position: "absolute",
              bottom: "calc(100% + 8px)",
              left: "50%",
              transform: `translateX(-50%) translateY(${hovered ? "0" : "4px"})`,
              padding: "3px 8px",
              borderRadius: 6,
              whiteSpace: "nowrap",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: 9,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: colors.text,
              background: "rgba(6,10,20,0.97)",
              border: `1px solid ${colors.primary}`,
              boxShadow: `0 4px 14px rgba(0,0,0,0.55)`,
              pointerEvents: "none",
              opacity: hovered ? 1 : 0,
              transition: "opacity 130ms ease, transform 130ms ease",
            }}
          >
            ⊙ inspect
            {/* downward caret */}
            <span
              style={{
                position: "absolute",
                top: "100%",
                left: "50%",
                width: 6,
                height: 6,
                marginLeft: -3,
                marginTop: -3,
                background: "rgba(6,10,20,0.97)",
                borderRight: `1px solid ${colors.primary}`,
                borderBottom: `1px solid ${colors.primary}`,
                transform: "rotate(45deg)",
              }}
            />
          </div>
          {/* Label is purely visual: pointer-events pass through to the 3D
              hitbox so there is no dead gap between the DOM label and the 3D
              body. Hover state is driven entirely by the hitbox. */}
          <div
            style={{
              ...labelStyle,
              transform: "none",
              pointerEvents: "none",
              // Dark solid ground so the light label text stays readable over
              // bright walls and grid alike; the technology colour is the border.
              background: hovered ? "rgba(10,16,30,0.96)" : "rgba(6,10,20,0.88)",
              color: colors.text,
              border: `1px solid ${colors.primary}`,
              boxShadow: hovered ? `0 0 16px ${colors.primary}88` : `0 1px 8px rgba(0,0,0,0.45)`,
              transition: "background 140ms ease, box-shadow 140ms ease",
            }}
          >
            {shortLabel(id)}
          </div>
        </div>
      </Html>
    </group>
  );
}

const axisTag = (color) => ({
  padding: "1px 6px",
  borderRadius: 5,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 12,
  fontWeight: 700,
  color,
  background: "rgba(3,6,15,0.92)",
  border: `1px solid ${color}`,
  boxShadow: `0 0 10px ${color}66`,
  transition: "opacity 160ms ease",
  transform: "translate(-50%, -50%)",
});

// The origin gizmo. Idle it is a short colour key in the corner; on hover the
// world dims and the X / Y / Z axes extend smoothly with labels - a quick
// legend for the room-local frame.
function OriginAxes({ span = 20 }) {
  const [hovered, setHovered] = useState(false);
  const dimRef = useRef();
  const xRef = useRef();
  const yRef = useRef();
  const zRef = useRef();
  const nodeRef = useRef();
  const AXIS = 5.5;
  const BASE = 2 / AXIS; // idle length fraction

  useFrame(({ clock }, delta) => {
    const dt = Math.min(delta || 0.05, 0.1);
    const tgt = hovered ? 1 : BASE;
    const k = Math.min(1, dt * 5);
    if (xRef.current) xRef.current.scale.x += (tgt - xRef.current.scale.x) * k;
    if (yRef.current) yRef.current.scale.y += (tgt - yRef.current.scale.y) * k;
    if (zRef.current) zRef.current.scale.z += (tgt - zRef.current.scale.z) * k;
    if (dimRef.current) {
      const o = hovered ? 0.58 : 0;
      dimRef.current.material.opacity += (o - dimRef.current.material.opacity) * k;
    }
    if (nodeRef.current) {
      nodeRef.current.scale.setScalar(1 + (hovered ? Math.sin(clock.getElapsedTime() * 3) * 0.08 : 0));
    }
  });

  return (
    <group>
      {/* Dim dome: draws over everything (depthTest off) and fades in on hover
          so the world recedes and the axes read. */}
      <mesh ref={dimRef} renderOrder={1}>
        <sphereGeometry args={[span * 2.2, 24, 24]} />
        <meshBasicMaterial color="#03060f" transparent opacity={0} side={THREE.BackSide} depthWrite={false} depthTest={false} />
      </mesh>

      {/* Hover target at the origin. */}
      <mesh
        position={[0, 0.6, 0]}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[1.5, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      <mesh ref={nodeRef} position={[0, 0.12, 0]} renderOrder={4}>
        <sphereGeometry args={[0.22, 16, 16]} />
        <meshStandardMaterial color="#e8eef7" emissive="#88b6ff" emissiveIntensity={0.6} depthTest={false} />
      </mesh>

      <group ref={xRef} scale={[BASE, 1, 1]}>
        <Line points={[[0, 0.08, 0], [AXIS, 0.08, 0]]} color="#ff5a6e" lineWidth={3} renderOrder={4} />
        <Html position={[AXIS, 0.08, 0]} center distanceFactor={14} zIndexRange={LABEL_Z} pointerEvents="none" wrapperClass="scene-label">
          <div style={{ ...axisTag("#ff5a6e"), opacity: hovered ? 1 : 0 }}>X</div>
        </Html>
      </group>

      <group ref={yRef} scale={[1, BASE, 1]}>
        <Line points={[[0, 0.08, 0], [0, AXIS, 0]]} color="#5aa0ff" lineWidth={3} renderOrder={4} />
        <Html position={[0, AXIS, 0]} center distanceFactor={14} zIndexRange={LABEL_Z} pointerEvents="none" wrapperClass="scene-label">
          <div style={{ ...axisTag("#5aa0ff"), opacity: hovered ? 1 : 0 }}>Y</div>
        </Html>
      </group>

      <group ref={zRef} scale={[1, 1, BASE]}>
        <Line points={[[0, 0.08, 0], [0, 0.08, AXIS]]} color="#5dffb0" lineWidth={3} renderOrder={4} />
        <Html position={[0, 0.08, AXIS]} center distanceFactor={14} zIndexRange={LABEL_Z} pointerEvents="none" wrapperClass="scene-label">
          <div style={{ ...axisTag("#5dffb0"), opacity: hovered ? 1 : 0 }}>Z</div>
        </Html>
      </group>
    </group>
  );
}

function WallMat() {
  return (
    <meshStandardMaterial
      color="#3a82ff"
      emissive="#1d3a73"
      emissiveIntensity={0.35}
      metalness={0.2}
      roughness={0.4}
      transparent
      opacity={0.35}
    />
  );
}

// Resolve the room perimeter into an ordered list of edges. Polygon-shaped
// rooms (`room.shape: [[x, y], ...]`) yield one edge per vertex pair;
// rectangle rooms fall back to the four cardinal sides in the convention
// shared with the placement-editor schema (0=N, 1=E, 2=S, 3=W). The 3D
// scene splits each edge around its openings - same lintel/sill logic as
// inner walls.
function _perimeterEdges(room, w, d) {
  if (room && Array.isArray(room.shape) && room.shape.length >= 3) {
    const baseX = Number(room.x_m) || 0;
    const baseY = Number(room.y_m) || 0;
    const pts = room.shape.map((p) => [
      Number(p[0]) - baseX,
      Number(p[1]) - baseY,
    ]);
    const edges = [];
    for (let i = 0; i < pts.length; i++) {
      const [x1, y1] = pts[i];
      const [x2, y2] = pts[(i + 1) % pts.length];
      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.hypot(dx, dy);
      if (length < 0.05) continue;
      edges.push({ start: [x1, y1], dir: [dx / length, dy / length], length });
    }
    return edges;
  }
  return [
    { start: [0, 0], dir: [1, 0], length: w },
    { start: [w, 0], dir: [0, 1], length: d },
    { start: [0, d], dir: [1, 0], length: w },
    { start: [0, 0], dir: [0, 1], length: d },
  ];
}

// Map legacy `side` perimeter openings to `edge_index` so the same
// rendering code works on both shapes.
function _normalizePerimeterOpening(o) {
  if (o.edge_index != null) return o;
  const sideToIndex = { N: 0, E: 1, S: 2, W: 3 };
  if (o.side != null && sideToIndex[o.side] != null) {
    return { ...o, edge_index: sideToIndex[o.side] };
  }
  return null;
}

function _cleanRanges(opens, sideLen) {
  const norm = (opens || [])
    .map((o) => {
      const a = Math.max(0, Math.min(sideLen, Number(o.start_m) || 0));
      const b = Math.max(0, Math.min(sideLen, Number(o.end_m) || 0));
      return {
        ...o,
        start_m: Math.min(a, b),
        end_m: Math.max(a, b),
        height_m: Number(o.height_m) || DEFAULT_OPENING_HEIGHT,
        sill_m: Number(o.sill_m) || 0,
      };
    })
    .filter((o) => o.end_m - o.start_m > 0.02)
    .sort((a, b) => a.start_m - b.start_m);
  const merged = [];
  for (const o of norm) {
    const last = merged[merged.length - 1];
    if (last && o.start_m <= last.end_m) {
      last.end_m = Math.max(last.end_m, o.end_m);
      last.height_m = Math.max(last.height_m, o.height_m);
      last.sill_m = Math.min(last.sill_m, o.sill_m);
    } else {
      merged.push({ ...o });
    }
  }
  const solid = [];
  let cursor = 0;
  for (const o of merged) {
    if (o.start_m > cursor + 0.01) solid.push({ start_m: cursor, end_m: o.start_m });
    cursor = Math.max(cursor, o.end_m);
  }
  if (cursor < sideLen - 0.01) solid.push({ start_m: cursor, end_m: sideLen });
  return { solid, openings: merged };
}

function PerimeterWalls({ room, w, d, height = DEFAULT_WALL_HEIGHT, openings = [] }) {
  const t = 0.15;
  const edges = _perimeterEdges(room, w, d);
  const normOpenings = (openings || [])
    .map(_normalizePerimeterOpening)
    .filter(Boolean);
  return (
    <group>
      {edges.map((edge, idx) => {
        const edgeOpens = normOpenings.filter(
          (o) => Number(o.edge_index) === idx
        );
        const { solid, openings: merged } = _cleanRanges(edgeOpens, edge.length);
        const [sx, sz] = edge.start;
        const angle = Math.atan2(edge.dir[1], edge.dir[0]);
        return (
          <group key={idx} position={[sx, 0, sz]} rotation={[0, -angle, 0]}>
            {solid.map((s, i) => (
              <WallBox
                key={`s${i}`}
                startM={s.start_m}
                endM={s.end_m}
                thickness={t}
                base={0}
                top={height}
              />
            ))}
            {merged.map((o, i) => {
              const topOfOpening = o.sill_m + o.height_m;
              return (
                <group key={`o${i}`}>
                  {topOfOpening < height && (
                    <WallBox
                      startM={o.start_m}
                      endM={o.end_m}
                      thickness={t}
                      base={topOfOpening}
                      top={height}
                    />
                  )}
                  {o.sill_m > 0.01 && (
                    <WallBox
                      startM={o.start_m}
                      endM={o.end_m}
                      thickness={t}
                      base={0}
                      top={o.sill_m}
                    />
                  )}
                </group>
              );
            })}
          </group>
        );
      })}
    </group>
  );
}

// Clean + merge wall openings the same way the editor does. Returns
// {solidSegments, openings} where each entry is { start_m, end_m } in
// wall-local distance from (x1, y1). Defensive against bad / overlapping
// schema input so the 3D scene degrades gracefully on partial data.
function segmentWall(wall, wlen) {
  const raw = Array.isArray(wall.openings) ? wall.openings : [];
  const clean = raw
    .map((o) => {
      const a = Math.max(0, Math.min(wlen, Number(o.start_m) || 0));
      const b = Math.max(0, Math.min(wlen, Number(o.end_m) || 0));
      return {
        ...o,
        start_m: Math.min(a, b),
        end_m: Math.max(a, b),
        height_m: Number(o.height_m) || DEFAULT_OPENING_HEIGHT,
        sill_m: Number(o.sill_m) || 0,
      };
    })
    .filter((o) => o.end_m - o.start_m > 0.02)
    .sort((a, b) => a.start_m - b.start_m);
  const merged = [];
  for (const o of clean) {
    const last = merged[merged.length - 1];
    if (last && o.start_m <= last.end_m) {
      last.end_m = Math.max(last.end_m, o.end_m);
      last.height_m = Math.max(last.height_m, o.height_m);
      last.sill_m = Math.min(last.sill_m, o.sill_m);
    } else {
      merged.push({ ...o });
    }
  }
  const solid = [];
  let cursor = 0;
  for (const o of merged) {
    if (o.start_m > cursor + 0.01) solid.push({ start_m: cursor, end_m: o.start_m });
    cursor = Math.max(cursor, o.end_m);
  }
  if (cursor < wlen - 0.01) solid.push({ start_m: cursor, end_m: wlen });
  return { solid, openings: merged };
}

// Single wall segment box centred at midpoint. wall-local x runs along the
// segment; the parent <group> rotates the whole thing into world space.
function WallBox({ startM, endM, thickness, base, top }) {
  const len = Math.max(0.01, endM - startM);
  const cx = (startM + endM) / 2;
  const height = Math.max(0.01, top - base);
  return (
    <mesh position={[cx, base + height / 2, 0]}>
      <boxGeometry args={[len, height, thickness]} />
      <WallMat />
      <Edges color="#7fb3ff" />
    </mesh>
  );
}

// Inner walls drawn from the placement-editor schema. Each wall is split
// into solid segments around openings (doors / windows). Openings get a
// faint frame so the gap reads as intentional, not missing geometry.
function InnerWalls({ walls, defaultHeight }) {
  if (!walls?.length) return null;
  return (
    <>
      {walls.map((wall, idx) => {
        const x1 = Number(wall.x1);
        const y1 = Number(wall.y1);
        const x2 = Number(wall.x2);
        const y2 = Number(wall.y2);
        const dx = x2 - x1;
        const dy = y2 - y1;
        const wlen = Math.hypot(dx, dy);
        if (!Number.isFinite(wlen) || wlen < 0.05) return null;
        const angle = Math.atan2(dy, dx);
        const t = Number(wall.thickness) || DEFAULT_WALL_THICK;
        const wallHeight = Number(wall.height_m) || defaultHeight;
        const { solid, openings } = segmentWall(wall, wlen);

        return (
          <group
            key={wall.id || `w${idx}`}
            position={[x1, 0, y1]}
            rotation={[0, -angle, 0]}
          >
            {solid.map((s, i) => (
              <WallBox
                key={`s${i}`}
                startM={s.start_m}
                endM={s.end_m}
                thickness={t}
                base={0}
                top={wallHeight}
              />
            ))}
            {openings.map((o, i) => {
              // Lintel above the opening keeps the wall continuous up to
              // the ceiling; sill segment below adds a windowsill when the
              // opening doesn't reach the floor.
              const topOfOpening = o.sill_m + o.height_m;
              return (
                <group key={`o${i}`}>
                  {topOfOpening < wallHeight && (
                    <WallBox
                      startM={o.start_m}
                      endM={o.end_m}
                      thickness={t}
                      base={topOfOpening}
                      top={wallHeight}
                    />
                  )}
                  {o.sill_m > 0.01 && (
                    <WallBox
                      startM={o.start_m}
                      endM={o.end_m}
                      thickness={t}
                      base={0}
                      top={o.sill_m}
                    />
                  )}
                </group>
              );
            })}
          </group>
        );
      })}
    </>
  );
}

function GradientTrail({ points, color }) {
  if (points.length < 2) return null;
  return <Line points={points} color={color} lineWidth={3} transparent opacity={0.65} />;
}

function ConnectionLines({ from, aps, color }) {
  if (!from || !aps?.length) return null;
  // Render one faint line per AP; opacity scales inversely with distance so
  // closer APs appear "more involved" without needing per-AP contribution data
  // from the adapter. Anchor z = ap.y (room-local canvas-y), the same frame
  // toLocal puts the device in, so the line lands on the dot.
  return aps.map((ap) => {
    const dist = Math.hypot(ap.x - from.x, ap.y - from.z);
    const opacity = Math.max(0.08, Math.min(0.6, 4 / (dist + 2)));
    return (
      <Line
        key={ap.id}
        points={[
          [from.x, 0.2, from.z],
          [ap.x, 0.9, ap.y],
        ]}
        color={color}
        lineWidth={1}
        transparent
        opacity={opacity}
        dashed
        dashSize={0.3}
        gapSize={0.2}
      />
    );
  });
}

function DeviceTracks({ positions, onSelectDevice, aps, frame }) {
  const trailsRef = useRef({});
  const lastSeenRef = useRef({});
  // Per-device smoothed position (EMA of toLocal output).
  const smoothedRef = useRef({});
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const keep = new Set(positions.map((p) => p.device.assetId));
    for (const k of Object.keys(trailsRef.current)) {
      if (!keep.has(k)) {
        delete trailsRef.current[k];
        delete lastSeenRef.current[k];
        delete smoothedRef.current[k];
      }
    }
  }, [positions]);

  return positions.map(({ device, position, selected = true }) => {
    const raw = toLocal(position?.area?.center, frame);
    const radius = position?.area?.radius ?? 0;
    const sources = position?.sources ?? [];
    const phone = device.assetId;

    if (position?.lastLocationTime) {
      if (lastSeenRef.current[phone] !== position.lastLocationTime) {
        lastSeenRef.current[phone] = position.lastLocationTime;
        if (raw) {
          const smoothed = ema2d(smoothedRef.current[phone], raw, EMA_ALPHA);
          smoothedRef.current[phone] = smoothed;

          const trail = trailsRef.current[phone] || [];
          const last = trail[trail.length - 1];
          if (!last || Math.hypot(last[0] - smoothed.x, last[2] - smoothed.z) >= 0.05) {
            trailsRef.current[phone] = [...trail, [smoothed.x, 0.15, smoothed.z]].slice(
              -TRAIL_MAX
            );
          }
        }
      }
    }

    const local = smoothedRef.current[phone] || raw;
    const trail = trailsRef.current[phone] || [];
    // Liveness is measured from observedAt (when the source last answered), not
    // from the fix time: a stationary asset keeps the same lastLocationTime yet
    // is still reachable. The trail above only grows on a NEW fix; staleness
    // here only greys a source that has gone silent. Grey the marker when the
    // source is silent OR its reported accuracy is worse than the display
    // threshold: a device far outside the calibrated room still yields a fresh
    // fix near the room centre with a huge radius, and a confident-looking dot
    // there would be a lie.
    const liveAt = position?.observedAt || position?.lastLocationTime;
    const tooOld = !liveAt || Date.now() - new Date(liveAt).getTime() > STALE_MS;
    const imprecise = radius != null && radius > ACCURACY_MAX_M;
    const stale = tooOld || imprecise;
    const hasWifi = sources.includes("wifi");

    return (
      <group key={phone}>
        {selected && hasWifi && !stale && local && (
          <ConnectionLines from={local} aps={aps} color={device.color} />
        )}
        {selected && <GradientTrail points={trail} color={device.color} />}
        {local && (
          <DeviceMarker
            x={local.x}
            z={local.z}
            radius={radius}
            label={device.label}
            color={device.color}
            stale={stale}
            hidden={!selected}
            onClick={onSelectDevice ? () => onSelectDevice(device) : undefined}
          />
        )}
      </group>
    );
  });
}

// A large gradient sky dome behind the scene: near-black overhead easing to a
// faint blue at the horizon, so the world sits in an open space, not a void.
// Ambient only (fog off, not raycastable) - never touches the room itself.
function GradientDome({ cx = 0, cz = 0, radius = 220 }) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        side: THREE.BackSide,
        depthWrite: false,
        fog: false,
        uniforms: {
          topColor: { value: new THREE.Color("#05070f") },
          horizonColor: { value: new THREE.Color("#16386f") },
          glowColor: { value: new THREE.Color("#2f6bd0") },
        },
        vertexShader:
          "varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
        fragmentShader:
          "varying vec3 vP; uniform vec3 topColor; uniform vec3 horizonColor; uniform vec3 glowColor; void main(){ float h = normalize(vP).y; float t = smoothstep(-0.03, 0.4, h); vec3 base = mix(horizonColor, topColor, t); float glow = smoothstep(0.14, 0.0, abs(h)) * 0.45; gl_FragColor = vec4(base + glowColor * glow, 1.0); }",
      }),
    []
  );
  return (
    <mesh position={[cx, 0, cz]} scale={radius} raycast={() => null}>
      <sphereGeometry args={[1, 40, 20]} />
      <primitive object={mat} attach="material" />
    </mesh>
  );
}

function Scene({ positions, layout, visibleTechs, relevantAnchorIds, onSelectDevice, onSelectAp }) {
  // Prefer v2 layout fields (rooms[0]) when present; legacy v1 (room_w / room_h /
  // aps / walls) still works as a fallback.
  const room = layout?.rooms?.[0] || null;
  const w = (room ? Number(room.width_m) : layout?.room_w) ?? FLOOR_W;
  const d = (room ? Number(room.height_m) : layout?.room_h) ?? FLOOR_D;
  const ceiling =
    Number(room?.wall_height_m) ||
    Number(layout?.wall_height_m) ||
    DEFAULT_WALL_HEIGHT;
  const allAps = (room?.anchors ?? layout?.aps) ?? [];
  const aps = visibleTechs
    ? allAps.filter((a) => visibleTechs.has(techOfAnchor(a)))
    : allAps;
  const walls = (room?.walls ?? layout?.walls) ?? [];
  const perimeterOpenings = room?.perimeter_openings ?? [];
  const cx = w / 2;
  const cz = d / 2;
  const extraW = w + 2 * MARGIN;
  const extraD = d + 2 * MARGIN;
  const span = Math.max(extraW, extraD);

  // Frame for projecting live device fixes (lat/lon) into this same room frame,
  // using the blueprint's floor-plan georef (shared by the engine/editor).
  const georef = layout?.floor_plans?.[0]?.georef || null;
  const frame =
    georef && georef.latitude != null && georef.longitude != null
      ? {
          georef: true,
          lat0: Number(georef.latitude),
          lon0: Number(georef.longitude),
          az: ((Number(georef.azimuth_deg) || 0) * Math.PI) / 180,
          roomX: Number(room?.x_m) || 0,
          roomY: Number(room?.y_m) || 0,
          fpH: Number(georef.height_m) || 0,
          d,
        }
      : null;

  return (
    <>
      <color attach="background" args={["#05070f"]} />
      <fog attach="fog" args={["#081025", 34, 105]} />
      <GradientDome cx={cx} cz={cz} />

      <ambientLight intensity={0.25} />
      <directionalLight position={[cx - 10, 18, cz - 10]} intensity={0.6} color="#9ec3ff" />
      <directionalLight position={[cx + 10, 14, cz + 10]} intensity={0.35} color="#ff9ec3" />
      {/* Soft overhead accent: gives the fixtures a highlight and adds depth. */}
      <pointLight position={[cx, 11, cz]} intensity={0.5} color="#7fb4ff" distance={span * 3} decay={2} />

      <Stars radius={160} depth={80} count={1800} factor={4} fade speed={0.25} />

      {/* outer halo plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, -0.04, cz]}>
        <planeGeometry args={[extraW * 1.6, extraD * 1.6]} />
        <meshBasicMaterial color="#0d1428" transparent opacity={0.9} />
      </mesh>

      {/* floor inside room */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, 0, cz]}>
        <planeGeometry args={[w, d]} />
        <meshStandardMaterial color="#0a1228" metalness={0.5} roughness={0.6} />
      </mesh>


      <Grid
        args={[extraW, extraD]}
        position={[cx, 0.02, cz]}
        cellSize={1}
        cellThickness={0.4}
        cellColor="#1d3160"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#3a82ff"
        fadeDistance={60}
        fadeStrength={3}
        infiniteGrid={true}
      />

      <PerimeterWalls
        room={room}
        w={w}
        d={d}
        height={ceiling}
        openings={perimeterOpenings}
      />
      <InnerWalls walls={walls} defaultHeight={ceiling} />
      <OriginAxes span={span} />

      {allAps.map((ap) => {
        // Anchors stay mounted when a layer is toggled off; `hidden` scales them
        // out (and back in) so appearance / disappearance is animated, not a pop.
        const hidden = visibleTechs ? !visibleTechs.has(techOfAnchor(ap)) : false;
        // With a focus, anchors outside the relevant set recede (dim palette);
        // no focus -> every anchor keeps its technology colour.
        const dimmed = relevantAnchorIds != null && !relevantAnchorIds.has(ap.id);
        return (
          <ApMarker
            key={ap.id}
            id={ap.id}
            x={ap.x}
            z={ap.y}
            height={Number(ap.height_m) || 1.2}
            ceiling={ceiling}
            hidden={hidden}
            colors={dimmed ? DIM_PALETTE : techPalette(ap)}
            onClick={onSelectAp ? () => onSelectAp(ap) : undefined}
          />
        );
      })}

      <DeviceTracks positions={positions} onSelectDevice={onSelectDevice} aps={aps} frame={frame} />
    </>
  );
}

// Smoothly fly the camera back to the home framing (position + room-centre
// target) on each recenter signal. Tween, not OrbitControls.reset(): reset
// can restore a target captured before the room-centre prop applied (it
// snapped to the corner), and it was instant. Drives invalidate() per frame
// so the demand-mode canvas renders the whole tween at full rate.
function CameraRig({ homePos, target, signal, controlsRef }) {
  const { camera, invalidate } = useThree();
  const anim = useRef(null);
  const home = useMemo(() => new THREE.Vector3(...homePos), [homePos]);
  const tgt = useMemo(() => new THREE.Vector3(...target), [target]);

  useEffect(() => {
    if (!signal) return; // skip the initial mount
    anim.current = {
      fromPos: camera.position.clone(),
      fromTgt: controlsRef.current ? controlsRef.current.target.clone() : tgt.clone(),
      t: 0,
    };
    invalidate();
  }, [signal]); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame((_, delta) => {
    const a = anim.current;
    if (!a) return;
    a.t = Math.min(1, a.t + delta / 0.55);
    const k = 1 - Math.pow(1 - a.t, 3); // easeOutCubic
    camera.position.lerpVectors(a.fromPos, home, k);
    const c = controlsRef.current;
    if (c) {
      c.target.lerpVectors(a.fromTgt, tgt, k);
      c.update();
    }
    invalidate();
    if (a.t >= 1) anim.current = null;
  });
  return null;
}

export function FloorPlanScene({ token, positions = [], visibleTechs, relevantAnchorIds, recenterSignal = 0, onSelectDevice, onSelectAp, onLayoutLoaded }) {
  const [layout, setLayout] = useState(null);
  const controlsRef = useRef();

  // The blueprint comes from the CAMARA gateway (which proxies the engine, the
  // blueprint authority). The demo is a MEC app: it talks only to the gateway,
  // never the engine directly. A 404 means no venue authored yet -> the scene
  // falls back to its default dimensions.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetch(`${CAMARA_API_BASE}/blueprint`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        setLayout(data);
        if (onLayoutLoaded) onLayoutLoaded(data);
      })
      .catch(() => {
        if (!cancelled) setLayout(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token, onLayoutLoaded]);

  const w = layout?.room_w ?? FLOOR_W;
  const d = layout?.room_h ?? FLOOR_D;
  const cx = w / 2;
  const cz = d / 2;
  const span = Math.max(w + 2 * MARGIN, d + 2 * MARGIN);

  // A marker selection stamps this; the canvas' empty-click handler ignores a
  // "miss" that lands right after a pick, so clicking a moving marker (whose
  // pointer-up can land off it) never closes the panel it just opened.
  const pickedAtRef = useRef(0);
  const pickDevice = (dv) => {
    pickedAtRef.current = Date.now();
    onSelectDevice?.(dv);
  };
  const pickAp = (ap) => {
    pickedAtRef.current = Date.now();
    onSelectAp?.(ap);
  };

  return (
    <div style={{ position: "relative", height: "100%", minHeight: 0 }}>
      {/* Bulletproof: scene labels (drei Html) must never intercept the raycast,
          otherwise a label sitting over a marker eats hover/click. drei only
          sets pointer-events on the inner div; force it off on the wrapper too. */}
      <style>{`.scene-label,.scene-label *{pointer-events:none !important}`}</style>
      <Canvas
        dpr={[1, 2]}
        frameloop="demand"
        camera={{ position: [cx + span * 0.32, span * 0.5, cz + span * 0.62], fov: 50 }}
        gl={{ antialias: true, powerPreference: "high-performance", toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.1 }}
        style={{ height: "100%", borderRadius: 0, background: "#070b18", touchAction: "none" }}
        onPointerMissed={() => {
          if (Date.now() - pickedAtRef.current < 250) return;
          onSelectDevice?.(null);
        }}
      >
        <RenderTick fps={30} />
        <Scene
          positions={positions}
          layout={layout}
          visibleTechs={visibleTechs}
          relevantAnchorIds={relevantAnchorIds}
          onSelectDevice={pickDevice}
          onSelectAp={pickAp}
        />
        <CameraRig
          homePos={[cx + span * 0.32, span * 0.5, cz + span * 0.62]}
          target={[cx, 0, cz]}
          signal={recenterSignal}
          controlsRef={controlsRef}
        />
        <OrbitControls
          ref={controlsRef}
          makeDefault
          target={[cx, 0, cz]}
          enableDamping
          dampingFactor={0.08}
          maxPolarAngle={Math.PI / 2.1}
          // Clamp the dolly so the room can't shrink to a dot or fly off.
          minDistance={span * 0.4}
          maxDistance={span * 1.9}
        />
      </Canvas>
    </div>
  );
}

// Demand-mode tick: invalidates the canvas at a fixed cadence so the small
// animations (rotation, ring pulse, halo) keep moving without paying for the
// default 60 fps loop. Switches itself off while the tab is hidden so a
// minimised window costs nothing.
function RenderTick({ fps = 12 }) {
  const { invalidate } = useThree();
  useEffect(() => {
    let id = null;
    const start = () => {
      if (id == null) id = setInterval(invalidate, 1000 / fps);
    };
    const stop = () => {
      if (id != null) {
        clearInterval(id);
        id = null;
      }
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [invalidate, fps]);
  return null;
}
