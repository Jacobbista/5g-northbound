import { useEffect, useRef, useState } from "react";
import { Grid, Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { DEVICE_LABEL, FLOOR_D, FLOOR_W, GPS_ORIGIN_LAT, GPS_ORIGIN_LON } from "../config";

const M_PER_DEG = 111320;
const TRAIL_MAX = 40;
const MARGIN = 6; // metres of "extra space" drawn around the real room
const STALE_MS = 10000; // no update for this long -> marker greys out

// Project a CAMARA area.center (lat/lon) onto local floor-plan metres (inverse of
// the engine's local->gps conversion). x = east, y = north (room frame).
function toLocal(center) {
  if (!center) return null;
  const x =
    (center.longitude - GPS_ORIGIN_LON) * M_PER_DEG * Math.cos((GPS_ORIGIN_LAT * Math.PI) / 180);
  const z = (center.latitude - GPS_ORIGIN_LAT) * M_PER_DEG;
  return { x, z };
}

const labelStyle = {
  padding: "2px 6px",
  borderRadius: 4,
  fontFamily: "sans-serif",
  fontSize: 12,
  whiteSpace: "nowrap",
  transform: "translateY(-50%)",
  pointerEvents: "none",
};

function DeviceMarker({ x, z, radius, label, stale }) {
  const ring = useRef();
  const color = stale ? "#9e9e9e" : "#1976d2";
  useFrame(({ clock }) => {
    if (!ring.current) return;
    if (stale) {
      ring.current.material.opacity = 0;
      return;
    }
    const t = (clock.getElapsedTime() % 1.5) / 1.5;
    ring.current.scale.setScalar(1 + t * 1.4);
    ring.current.material.opacity = 0.6 * (1 - t);
  });

  return (
    <group position={[x, 0, z]}>
      <mesh position={[0, 0.5, 0]}>
        <boxGeometry args={[0.5, 1, 0.5]} />
        <meshStandardMaterial color={color} />
      </mesh>
      {radius > 0 && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
          <circleGeometry args={[radius, 48]} />
          <meshBasicMaterial color={color} transparent opacity={0.12} />
        </mesh>
      )}
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}>
        <ringGeometry args={[0.6, 0.9, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.6} />
      </mesh>
      <Html position={[0, 1.6, 0]} center>
        <div style={{ ...labelStyle, background: color, color: "#fff" }}>
          {label}
          {stale ? " (stale)" : ""}
        </div>
      </Html>
    </group>
  );
}

function ApMarker({ id, x, z }) {
  return (
    <group position={[x, 0, z]}>
      <mesh position={[0, 0.4, 0]}>
        <coneGeometry args={[0.35, 0.8, 4]} />
        <meshStandardMaterial color="#e67e22" />
      </mesh>
      <Html position={[0, 1.0, 0]} center>
        <div style={{ ...labelStyle, background: "#fff3e0", color: "#9a4a00", border: "1px solid #e67e22" }}>
          {id}
        </div>
      </Html>
    </group>
  );
}

// Axes at the measured origin (0,0): red = X (width), green = Y (length).
function OriginAxes() {
  const L = 5;
  return (
    <group>
      <mesh position={[0, 0.15, 0]}>
        <sphereGeometry args={[0.35, 16, 16]} />
        <meshStandardMaterial color="#1a1a1a" />
      </mesh>
      <Line points={[[0, 0.08, 0], [L, 0.08, 0]]} color="#c0392b" lineWidth={4} />
      <Line points={[[0, 0.08, 0], [0, 0.08, L]]} color="#27ae60" lineWidth={4} />
      <Html position={[L + 0.6, 0.15, 0]} center>
        <div style={{ ...labelStyle, background: "#c0392b", color: "#fff" }}>X → (width)</div>
      </Html>
      <Html position={[0, 0.15, L + 0.6]} center>
        <div style={{ ...labelStyle, background: "#27ae60", color: "#fff" }}>Y → (length)</div>
      </Html>
      <Html position={[0, 1.1, 0]} center>
        <div style={{ ...labelStyle, background: "#1a1a1a", color: "#fff" }}>origin 0,0</div>
      </Html>
    </group>
  );
}

// Coordinate label at each corner of the real room.
function CornerLabels({ w, d }) {
  const corners = [[0, 0], [w, 0], [0, d], [w, d]];
  return corners.map(([x, z]) => (
    <Html key={`${x},${z}`} position={[x, 0.2, z]} center>
      <div style={{ ...labelStyle, background: "#fff", color: "#333", border: "1px solid #999", fontSize: 11 }}>
        {x},{z}
      </div>
    </Html>
  ));
}

export function FloorPlanScene({ position }) {
  const [layout, setLayout] = useState(null);
  const [trail, setTrail] = useState([]);
  const [lastSeen, setLastSeen] = useState(Date.now());
  const [, setTick] = useState(0);

  useEffect(() => {
    fetch("/layout.json")
      .then((r) => (r.ok ? r.json() : null))
      .then(setLayout)
      .catch(() => setLayout(null));
  }, []);

  // 1 Hz tick so staleness re-evaluates even without new positions
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const local = toLocal(position?.area?.center);
  const radius = position?.area?.radius ?? 0;

  useEffect(() => {
    if (!position?.lastLocationTime) return;
    setLastSeen(Date.now());
    if (!local) return;
    setTrail((prev) => {
      const last = prev[prev.length - 1];
      if (last && Math.hypot(last[0] - local.x, last[2] - local.z) < 0.05) return prev;
      return [...prev, [local.x, 0.1, local.z]].slice(-TRAIL_MAX);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [position?.lastLocationTime]);

  const stale = Date.now() - lastSeen > STALE_MS;

  const w = layout?.room_w ?? FLOOR_W;
  const d = layout?.room_h ?? FLOOR_D;
  const aps = layout?.aps ?? [];
  const cx = w / 2;
  const cz = d / 2;
  const extraW = w + 2 * MARGIN;
  const extraD = d + 2 * MARGIN;
  const span = Math.max(extraW, extraD);

  return (
    <Canvas camera={{ position: [cx + span * 0.35, span * 0.85, cz + span * 0.8], fov: 50 }} style={{ height: "80vh" }}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[cx, 20, cz]} intensity={0.7} />

      {/* extra space (adjacent rooms) — light grey */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, -0.02, cz]}>
        <planeGeometry args={[extraW, extraD]} />
        <meshStandardMaterial color="#ededed" />
      </mesh>
      {/* the actual room (w x d) — darker grey */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, 0, cz]}>
        <planeGeometry args={[w, d]} />
        <meshStandardMaterial color="#bdbdbd" />
      </mesh>

      <Grid
        args={[extraW, extraD]}
        position={[cx, 0.01, cz]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#b8b8b8"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#888"
        fadeDistance={150}
        infiniteGrid={false}
      />

      <OriginAxes />
      <CornerLabels w={w} d={d} />

      {aps.map((ap) => (
        <ApMarker key={ap.id} id={ap.id} x={ap.x} z={ap.y} />
      ))}

      {trail.length > 1 && <Line points={trail} color="#1976d2" lineWidth={2} transparent opacity={0.5} />}

      {local && <DeviceMarker x={local.x} z={local.z} radius={radius} label={DEVICE_LABEL} stale={stale} />}

      <OrbitControls target={[cx, 0, cz]} />
    </Canvas>
  );
}
