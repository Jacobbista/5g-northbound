import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

// Raycast gating for markers while an asset is being carried. Both branches
// are real functions. R3F writes a function prop straight onto the instance,
// so `raycast={undefined}` sets an own property that shadows
// Mesh.prototype.raycast; three then throws "raycast is not a function" on
// the next pointer move and the canvas' whole event pipeline dies with it.
const NO_RAYCAST = () => null;
const MESH_RAYCAST = THREE.Mesh.prototype.raycast;

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
// The blueprint changes only on an operator's action in the placement editor
// (georef, room size, anchor positions), not on the demo's own cadence, so a
// slow poll is enough. Without it, a tab open across such an edit keeps
// projecting fresh WGS84 fixes onto the room's old frame: the dot visibly
// drifts off where the anchors and walls now are, and only a reload (which
// re-fetches once, on mount) corrects it. Matches useAdapterHealth's poll.
const BLUEPRINT_POLL_MS = 15000;
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

function DeviceMarker({ x, z, radius, label, color, stale, hidden = false, inert = false, onClick }) {
  const groupRef = useRef();
  const ring = useRef();
  const glow = useRef();
  const bodyRef = useRef();
  const renderColor = stale ? "#5a6470" : color;

  // Seed the position so the marker never lerps in from the origin, and start
  // at zero scale so it grows into place. Arriving markers otherwise pop at
  // full size, which is most visible right after a placement, where it lands
  // on top of the mark left by the drop.
  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.set(x, 0, z);
      groupRef.current.scale.setScalar(0);
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
        // Out of the raycast entirely while an asset is being placed: a marker
        // that handles the move stops it reaching the block being carried.
        raycast={inert ? NO_RAYCAST : MESH_RAYCAST}
        onPointerDown={(e) => {
          if (hidden || inert || !onClick) return;
          e.stopPropagation();
          onClick();
        }}
        onPointerOver={(e) => {
          if (inert) return;
          if (hidden || inert) return;
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

function ApMarker({ id, x, z, height = 1.2, ceiling = DEFAULT_WALL_HEIGHT, hidden = false, inert = false, colors = TECH_PALETTE.wifi, onClick }) {
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
        // See DeviceMarker: inert while a placement is in progress.
        raycast={inert ? NO_RAYCAST : MESH_RAYCAST}
        onPointerDown={(e) => {
          if (hidden || inert || !onClick) return;
          e.stopPropagation();
          onClick();
        }}
        onPointerOver={(e) => {
          if (hidden || inert) return;
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
function OriginAxes({ span = 20, inert = false }) {
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
        raycast={inert ? NO_RAYCAST : MESH_RAYCAST}
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

function DeviceTracks({ positions, onSelectDevice, wifiAps, frame, inert = false }) {
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
          <ConnectionLines from={local} aps={wifiAps} color={device.color} />
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
            inert={inert}
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
// Placing an asset: the block appears floating over the middle of the room,
// and you carry it where you want it. Not an HTML drag: the thing being moved
// is the marker the scene will keep, so what you pick up is what will be there.
//
// The scene renders the room at world x in [0, w], z in [0, d] with no
// transform, so a hit on the floor plane IS the room-local coordinate the
// placement API takes.
// How high the block waits, as a fraction of how far the camera is from it.
// A fixed height in metres reads as a hop when the view is pulled back and as
// a tower when it is close in; tying it to the distance keeps the gap between
// block and floor about the same on screen at any zoom. Clamped so a very
// tight or very wide view stays sane.
const HOVER_RATIO = 0.22;
const HOVER_MIN_M = 3.5;
const HOVER_MAX_M = 16.0;
const FALL_S = 0.55;        // how long the drop takes
const FOLLOW_RATE = 7.0;    // how hard the block chases the hand per second
const RETURN_RATE = 2.6;    // how fast it drifts home when released outside
const TILT_MAX = 0.5;       // radians of bank at full speed
const TILT_PER_MS = 0.16;   // lateral speed that reaches full bank
const REFUSED = "#ff6b78";
// Clearance kept from a wall face, on top of its own half-thickness. An asset
// sitting flush inside masonry is not a place it could be.
const WALL_CLEARANCE_M = 0.35;

// Do two segments cross? Used to count the walls standing between two points.
function segmentsCross(ax, az, bx, bz, cx, cz, dx, dz) {
  const r1 = (bx - ax) * (cz - az) - (bz - az) * (cx - ax);
  const r2 = (bx - ax) * (dz - az) - (bz - az) * (dx - ax);
  const r3 = (dx - cx) * (az - cz) - (dz - cz) * (ax - cx);
  const r4 = (dx - cx) * (bz - cz) - (dz - cz) * (bx - cx);
  return r1 * r2 < 0 && r3 * r4 < 0;
}

// The solid stretches of a wall, in room-local metres, with doorways removed.
function solidSpans(wall) {
  const x1 = Number(wall.x1);
  const z1 = Number(wall.y1);
  const x2 = Number(wall.x2);
  const z2 = Number(wall.y2);
  const len = Math.hypot(x2 - x1, z2 - z1);
  if (!Number.isFinite(len) || len < 0.05) return [];
  const ux = (x2 - x1) / len;
  const uz = (z2 - z1) / len;
  return segmentWall(wall, len).solid.map((sp) => ({
    ax: x1 + ux * sp.start_m,
    az: z1 + uz * sp.start_m,
    bx: x1 + ux * sp.end_m,
    bz: z1 + uz * sp.end_m,
  }));
}

// How many solid walls stand between two points. Doorways do not count, so a
// room you could walk into reads as reachable and a sealed box does not.
function wallsBetween(fromX, fromZ, toX, toZ, walls) {
  let n = 0;
  for (const wall of walls) {
    for (const sp of solidSpans(wall)) {
      if (segmentsCross(fromX, fromZ, toX, toZ, sp.ax, sp.az, sp.bx, sp.bz)) n += 1;
    }
  }
  return n;
}

// Distance from a point to a wall segment, both in room-local metres.
function distanceToWall(px, pz, wall) {
  const x1 = Number(wall.x1);
  const z1 = Number(wall.y1);
  const x2 = Number(wall.x2);
  const z2 = Number(wall.y2);
  const dx = x2 - x1;
  const dz = z2 - z1;
  const len2 = dx * dx + dz * dz;
  if (!Number.isFinite(len2) || len2 < 1e-6) return Infinity;
  // Project onto the segment, clamped to its ends.
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (pz - z1) * dz) / len2));
  return Math.hypot(px - (x1 + t * dx), pz - (z1 + t * dz));
}

function PlacementGhost({ color = "#5dffb0", label, w, d, walls = [], onDrop, onCancel, onGrabChange }) {
  const { camera, gl } = useThree();
  const bodyRef = useRef();
  const groupRef = useRef();
  const home = useMemo(() => ({ x: w / 2, z: d / 2 }), [w, d]);
  // Read every frame rather than on every event, so the block moves at frame
  // rate and the carry stays smooth.
  const targetRef = useRef(null);
  const stateRef = useRef({ ...home, vx: 0, vz: 0, born: 0, held: false, fall: null });
  // Driven per frame from the camera distance, and used for the body height,
  // the tether length and the drop, so the three never disagree.
  const hoverRef = useRef(HOVER_MIN_M);
  const tetherRef = useRef();
  // Read inside a handler that must not be rebuilt on every blueprint render.
  const wallsRef = useRef(walls);
  wallsRef.current = walls;
  // Only for the label and the ring colour; the carry itself is ref-driven.
  const [ui, setUi] = useState({ held: false, inside: true });

  // A point is droppable when it is inside the room AND clear of its walls.
  // The room bounds alone let an asset land inside a partition, which is a
  // place it could never be and which the walker would have to shove it out of.
  const inside = (p) => {
    if (!p || p.x < 0 || p.x > w || p.z < 0 || p.z > d) return false;
    const walls = wallsRef.current;
    // Not inside the masonry itself.
    for (const wall of walls) {
      const half = (Number(wall.thickness) || DEFAULT_WALL_THICK) / 2;
      if (distanceToWall(p.x, p.z, wall) < half + WALL_CLEARANCE_M) return false;
    }
    // And not shut inside a partition. An odd number of solid walls between
    // the point and the open floor means it is enclosed, which is a place the
    // asset could not walk to and could not leave: dropped there it would sit
    // against the inside of a box forever.
    return wallsBetween(w / 2, d / 2, p.x, p.z, walls) % 2 === 0;
  };

  // Where the cursor ray crosses the horizontal plane the block floats on.
  //
  // This is the whole trick, and getting it wrong is what made the block
  // either jump on grab or trail off somewhere else. The cursor points AT the
  // block, which is in the air. Projecting that ray onto the FLOOR gives a
  // point well past it, so following the floor point moves the block to
  // somewhere the hand never indicated. Projecting onto the plane at the
  // block's own height keeps it exactly under the cursor, with nothing to
  // correct for.
  const planeAt = (ray, y) => {
    if (!ray || Math.abs(ray.direction.y) < 1e-6) return null;
    const t = (y - ray.origin.y) / ray.direction.y;
    if (t <= 0) return null;
    return {
      x: ray.origin.x + ray.direction.x * t,
      z: ray.origin.z + ray.direction.z * t,
    };
  };

  const release = useCallback(() => {
    const st = stateRef.current;
    if (!st.held || st.fall) return;
    st.held = false;
    onGrabChange?.(false);
    document.body.style.cursor = "auto";
    const point = targetRef.current;
    if (inside(point)) {
      st.fall = { t: 0, from: hoverRef.current };
      // Hand the point over now, not when the fall ends: the call goes out
      // while the block is still in the air, so the network overlaps the
      // animation instead of following it.
      onDrop?.({ x: st.x, z: st.z });
    } else {
      // Released over nothing. It drifts back over the room rather than being
      // dropped somewhere the asset could not be.
      targetRef.current = null;
    }
    setUi({ held: false, inside: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onDrop, onGrabChange, w, d]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onCancel?.();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerup", release);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerup", release);
    };
  }, [onCancel, release]);

  // While the block is held the pointer is read straight from the window,
  // not through the scene's own event system. Anything the cursor crosses on
  // the way - an anchor, a marker, a label - handles the move and stops it
  // travelling, which starved the carry and made it stutter. Nothing can
  // intercept this.
  useEffect(() => {
    if (!ui.held) return;
    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const onMove = (ev) => {
      const st = stateRef.current;
      if (!st.held || st.fall) return;
      const rect = gl.domElement.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      ndc.set(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(ndc, camera);
      const point = planeAt(raycaster.ray, hoverRef.current);
      if (!point) return;
      targetRef.current = point;
      const now = inside(point);
      setUi((cur) => (cur.inside === now ? cur : { held: true, inside: now }));
    };
    window.addEventListener("pointermove", onMove);
    return () => window.removeEventListener("pointermove", onMove);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ui.held, camera, gl, w, d]);

  useEffect(() => {
    const st = stateRef.current;
    st.x = home.x;
    st.z = home.z;
    st.born = performance.now() / 1000;
    return () => onGrabChange?.(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFrame(({ clock, camera }, delta) => {
    const dt = Math.min(delta || 0.016, 0.05);
    const st = stateRef.current;
    const g = groupRef.current;
    const b = bodyRef.current;
    if (!g || !b) return;
    const t = clock.getElapsedTime();

    // Follow the view, smoothed, so a zoom does not snap the block upward.
    const dist = camera.position.distanceTo(g.position);
    const want = Math.max(HOVER_MIN_M, Math.min(HOVER_MAX_M, dist * HOVER_RATIO));
    hoverRef.current += (want - hoverRef.current) * Math.min(1, dt * 3);
    const hover = hoverRef.current;
    if (tetherRef.current) tetherRef.current.scale.y = hover;

    if (st.fall) {
      // Ease in: slow off the top, quickest just before it lands, so it reads
      // as falling rather than sliding down. It also stops spinning and levels
      // out, which settles the eye on the landing point.
      st.fall.t = Math.min(1, st.fall.t + dt / FALL_S);
      const k = st.fall.t * st.fall.t;
      // Falls from wherever it was waiting, not from a fixed height.
      b.position.y = st.fall.from * (1 - k);
      b.rotation.x += (0 - b.rotation.x) * Math.min(1, dt * 6);
      b.rotation.z += (0 - b.rotation.z) * Math.min(1, dt * 6);
      b.rotation.y += dt * 1.2 * (1 - k);
      const squash = st.fall.t >= 1 ? 1 : 1 + k * 0.12;
      b.scale.set(1 / squash, squash, 1 / squash);
      return;
    }

    // Materialise: grow from nothing with a slight overshoot, so it arrives
    // rather than blinking into place.
    const age = t - st.born;
    const grow = Math.min(1, age / 0.4);
    const pop = 1 + Math.sin(Math.min(1, age / 0.4) * Math.PI) * 0.2;
    b.scale.setScalar(grow * pop);

    // Held: chase the hand with lag, so it trails rather than being welded to
    // the cursor. Loose: drift back over the middle of the room.
    const target = st.held && targetRef.current ? targetRef.current : home;
    const rate = st.held ? FOLLOW_RATE : RETURN_RATE;
    const px = st.x;
    const pz = st.z;
    const k = Math.min(1, rate * dt);
    st.x += (target.x - st.x) * k;
    st.z += (target.z - st.z) * k;
    st.vx = (st.x - px) / dt;
    st.vz = (st.z - pz) / dt;
    g.position.set(st.x, 0, st.z);

    // Bank into the direction of travel, the way a carried thing swings.
    const tiltX = Math.max(-TILT_MAX, Math.min(TILT_MAX, st.vz * TILT_PER_MS));
    const tiltZ = Math.max(-TILT_MAX, Math.min(TILT_MAX, -st.vx * TILT_PER_MS));
    b.rotation.x += (tiltX - b.rotation.x) * Math.min(1, dt * 7);
    b.rotation.z += (tiltZ - b.rotation.z) * Math.min(1, dt * 7);
    b.rotation.y += dt * 0.6;
    // One height, held or not. Changing it on grab made the block dip the
    // moment it was taken, which read as it slipping rather than being lifted.
    const rest = hover;
    b.position.y += (rest + Math.sin(t * 1.8) * 0.14 - b.position.y) * Math.min(1, dt * 5);
  });

  const showRefused = ui.held && !ui.inside;
  const ringColor = showRefused ? REFUSED : color;
  const caption = stateRef.current.fall
    ? ""
    : ui.held
      ? (ui.inside ? "release to drop it here" : "outside the room")
      : "drag it into the room";

  return (
    <group>
      <group ref={groupRef}>
        {/* Where it would land, and the line joining the two, so the point is
            unambiguous from any camera angle. */}
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]} raycast={() => null}>
          <ringGeometry args={[0.66, 0.8, 48]} />
          <meshBasicMaterial color={ringColor} transparent opacity={showRefused ? 0.5 : 0.7} />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]} raycast={() => null}>
          <circleGeometry args={[0.66, 48]} />
          <meshBasicMaterial color={ringColor} transparent opacity={0.1} />
        </mesh>
        {/* Unit tether, scaled per frame to the current hover, so its length
            always joins the block to its landing point. */}
        <group ref={tetherRef} position={[0, 0.06, 0]}>
          <Line
            points={[[0, 0, 0], [0, 1, 0]]}
            color={ringColor}
            lineWidth={1}
            dashed
            dashSize={0.05}
            gapSize={0.04}
            transparent
            opacity={0.45}
          />
        </group>

        <group ref={bodyRef} position={[0, HOVER_MIN_M, 0]}>
          {/* The block is the grab target. A generous invisible hitbox, since
              the body itself is small and a miss would feel like a dead click. */}
          <mesh
            onPointerDown={(e) => {
              const st = stateRef.current;
              if (st.fall) return;
              e.stopPropagation();
              st.held = true;
              // Taken at its own height, so the grab point is where the block
              // already is: it does not move at the moment it is picked up.
              const at = planeAt(e.ray, hoverRef.current);
              targetRef.current = at || { x: st.x, z: st.z };
              onGrabChange?.(true);
              setUi({ held: true, inside: inside(targetRef.current) });
              document.body.style.cursor = "grabbing";
            }}
            onPointerOver={(e) => {
              e.stopPropagation();
              document.body.style.cursor = "grab";
            }}
            onPointerOut={() => {
              document.body.style.cursor = "auto";
            }}
          >
            <sphereGeometry args={[1.1, 16, 12]} />
            <meshBasicMaterial transparent opacity={0} depthWrite={false} />
          </mesh>

          <mesh raycast={() => null}>
            <octahedronGeometry args={[0.45, 0]} />
            <meshStandardMaterial
              color={showRefused ? REFUSED : color}
              emissive={showRefused ? REFUSED : color}
              emissiveIntensity={0.8}
              transparent
              opacity={0.9}
            />
          </mesh>

          {caption && (
            <Html center distanceFactor={16} position={[0, 1.15, 0]} className="scene-label">
              <div
                style={{
                  whiteSpace: "nowrap",
                  fontFamily: "ui-monospace, monospace",
                  fontSize: 10.5,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: showRefused ? REFUSED : color,
                  background: "rgba(7,11,24,0.85)",
                  border: `1px solid ${showRefused ? REFUSED : color}55`,
                  borderRadius: 6,
                  padding: "3px 8px",
                }}
              >
                {label} · {caption}
              </div>
            </Html>
          )}
        </group>
      </group>
    </group>
  );
}


// Holds the landing point while the placed asset makes its way back through
// the fabric. Without it the block lands, vanishes, and the real marker turns
// up a beat later, which reads as the drop having failed.
function PlacementSettling({ x, z, color = "#5dffb0", fading = false, onDone }) {
  const inner = useRef();
  const outer = useRef();
  const fadeRef = useRef(1);
  useFrame(({ clock }, delta) => {
    const t = clock.getElapsedTime();
    // Once the asset is really there, this eases out underneath it rather than
    // being cut, so the two overlap for a moment instead of flicking over.
    if (fading) {
      fadeRef.current = Math.max(0, fadeRef.current - (delta || 0.016) / 0.35);
      if (fadeRef.current <= 0) onDone?.();
    }
    const k = fadeRef.current;
    if (inner.current) inner.current.material.opacity = (0.45 + Math.sin(t * 6) * 0.18) * k;
    if (outer.current) {
      const p = (t % 1.1) / 1.1;
      outer.current.scale.setScalar(1 + p * 1.6);
      outer.current.material.opacity = 0.5 * (1 - p) * k;
    }
  });
  return (
    <group position={[x, 0, z]}>
      <mesh ref={inner} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]} raycast={() => null}>
        <circleGeometry args={[0.6, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.45} />
      </mesh>
      <mesh ref={outer} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.07, 0]} raycast={() => null}>
        <ringGeometry args={[0.6, 0.74, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.5} />
      </mesh>
    </group>
  );
}


// Taking an asset off the plan. The marker would otherwise simply stop being
// drawn, which reads as a glitch rather than as something the operator did.
function PlacementVanishing({ x, z, color = "#5dffb0", onDone }) {
  const body = useRef();
  const ring = useRef();
  const t0 = useRef(null);
  useFrame(({ clock }) => {
    const now = clock.getElapsedTime();
    if (t0.current === null) t0.current = now;
    const p = Math.min(1, (now - t0.current) / 0.55);
    if (body.current) {
      // Lifts and shrinks away rather than fading in place, so the eye follows
      // it off the floor.
      body.current.position.y = 0.6 + p * 2.2;
      body.current.scale.setScalar(Math.max(0.001, 1 - p));
      body.current.rotation.y = p * 4;
      body.current.material.opacity = 0.9 * (1 - p);
    }
    if (ring.current) {
      ring.current.scale.setScalar(1 + p * 1.4);
      ring.current.material.opacity = 0.6 * (1 - p);
    }
    if (p >= 1) onDone?.();
  });
  return (
    <group position={[x, 0, z]}>
      <mesh ref={body} position={[0, 0.6, 0]} raycast={() => null}>
        <octahedronGeometry args={[0.45, 0]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} transparent opacity={0.9} />
      </mesh>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]} raycast={() => null}>
        <ringGeometry args={[0.6, 0.74, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.6} />
      </mesh>
    </group>
  );
}


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

function Scene({ positions, layout, visibleTechs, relevantAnchorIds, onSelectDevice, onSelectAp, inert = false }) {
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
  // ConnectionLines draws a trilateration line per AP for a wifi-sourced
  // device. Restricted to wifi anchors: `aps` above is only filtered by the
  // WIFI/UWB visibility toggle, so with both toggles on it would otherwise
  // include UWB anchors a wifi fix never ranged against.
  const wifiAps = aps.filter((a) => techOfAnchor(a) === "wifi");
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
      <OriginAxes span={span} inert={inert} />

      {allAps.map((ap) => {
        // Anchors stay mounted when a layer is toggled off; `hidden` scales them
        // out (and back in) so appearance / disappearance is animated, not a pop.
        const hidden = visibleTechs ? !visibleTechs.has(techOfAnchor(ap)) : false;
        // With a focus, anchors outside the relevant set recede (dim palette);
        // no focus -> every anchor keeps its technology colour.
        const dimmed = relevantAnchorIds != null && !relevantAnchorIds.has(ap.id);
        return (
          <ApMarker
            inert={inert}
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

      <DeviceTracks positions={positions} onSelectDevice={onSelectDevice} wifiAps={wifiAps} frame={frame} inert={inert} />
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

export function FloorPlanScene({ token, positions = [], visibleTechs, relevantAnchorIds, recenterSignal = 0, onSelectDevice, onSelectAp, onLayoutLoaded, placing = null, settling = null, vanishing = null, onPlaced, onCancelPlacing, onSettled, onVanished }) {
  const [layout, setLayout] = useState(null);
  const controlsRef = useRef();
  // True while the block is being carried. The scene stops taking pointer
  // events for as long as it is: the carry is driven from the window, so
  // nothing in the scene needs them, and letting anchors and markers light up
  // under a cursor that is busy moving something else is only noise.
  const [carrying, setCarrying] = useState(false);

  // The blueprint comes from the CAMARA gateway (which proxies the engine, the
  // blueprint authority). The demo is a MEC app: it talks only to the gateway,
  // never the engine directly. A 404 means no venue authored yet -> the scene
  // falls back to its default dimensions.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    let timer = null;

    const tick = async () => {
      try {
        const r = await fetch(`${CAMARA_API_BASE}/blueprint`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = r.ok ? await r.json() : null;
        if (cancelled) return;
        setLayout(data);
        if (onLayoutLoaded) onLayoutLoaded(data);
      } catch {
        // Transient failure: keep the last-known layout rather than dropping
        // to the default dimensions, matching useAdapterHealth's posture.
      } finally {
        if (!cancelled) timer = setTimeout(tick, BLUEPRINT_POLL_MS);
      }
    };
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [token, onLayoutLoaded]);

  // Same derivation Scene uses to draw the room, so the placement bounds and
  // the drawn walls can never describe different rooms. Reading only the
  // legacy top-level fields happened to agree on the current blueprint and
  // would not on one that carries rooms[] alone.
  const room0 = layout?.rooms?.[0] || null;
  const w = (room0 ? Number(room0.width_m) : layout?.room_w) ?? FLOOR_W;
  const d = (room0 ? Number(room0.height_m) : layout?.room_h) ?? FLOOR_D;
  const walls = (room0?.walls ?? layout?.walls) ?? [];
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
        style={{
          height: "100%",
          borderRadius: 0,
          background: "#070b18",
          touchAction: "none",
          pointerEvents: carrying ? "none" : "auto",
        }}
        onPointerMissed={() => {
          if (placing) return;
          if (Date.now() - pickedAtRef.current < 250) return;
          onSelectDevice?.(null);
        }}
      >
        <RenderTick fps={30} />
        {placing && (
          <PlacementGhost
            color={placing.color}
            label={placing.label}
            w={w}
            d={d}
            walls={walls}
            onDrop={(point) => onPlaced?.(placing.assetId, point)}
            onCancel={() => onCancelPlacing?.()}
            // Carrying the block and orbiting the camera are the same gesture.
            // While it is held the camera stays put, or the room swings around
            // under the thing being positioned.
            onGrabChange={(held) => {
              setCarrying(held);
              const c = controlsRef.current;
              if (c) c.enabled = !held;
            }}
          />
        )}
        {settling && (
          <PlacementSettling
            x={settling.x}
            z={settling.z}
            color={settling.color}
            fading={settling.fading}
            onDone={() => onSettled?.(settling.assetId)}
          />
        )}
        {vanishing && (
          <PlacementVanishing
            x={vanishing.x}
            z={vanishing.z}
            color={vanishing.color}
            onDone={() => onVanished?.(vanishing.assetId)}
          />
        )}
        <Scene
          inert={Boolean(placing)}
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
