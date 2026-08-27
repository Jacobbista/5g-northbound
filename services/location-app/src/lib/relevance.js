// Which anchors are relevant to the currently focused asset.
//
// Focus drives decluttering: the anchors that actually contribute to the
// focused asset's fix are highlighted, the rest dimmed. Returns a Set of
// anchor ids, or null when there is no focus (no relevance filter - the scene
// shows everything neutrally).
//
// - A UWB asset with `neighbors` (the anchors that ranged the tag, from the
//   diagnostics extension) -> the anchors whose vendor_device_id is a neighbor.
//   The join is by vendor_device_id, which the vendor-sync writes onto the
//   blueprint anchor.
// - Otherwise (wifi, or UWB with no neighbor data yet) -> every anchor of the
//   focused asset's own technology (the trilateration / same-radio set).
export function relevantAnchorIds(focus, anchors) {
  if (!focus || !focus.technology) return null;
  const list = anchors || [];
  const neighbors = Array.isArray(focus.neighbors) ? focus.neighbors : null;
  if (neighbors && neighbors.length > 0) {
    const wanted = new Set(neighbors.map(String));
    const ids = list
      .filter((a) => a.vendor_device_id != null && wanted.has(String(a.vendor_device_id)))
      .map((a) => a.id);
    if (ids.length > 0) return new Set(ids);
    // Neighbors named but none matched a placed anchor: fall through to the
    // technology set rather than dimming everything.
  }
  return new Set(
    list
      .filter((a) => (a.technology || "wifi") === focus.technology)
      .map((a) => a.id)
  );
}
