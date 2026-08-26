// Upsert a vendor-synced anchor into a room's anchor list.
//
// Anchors join to the cloud by `vendor_device_id`. A device already on the
// blueprint moves to its new position with its editor id kept; a new one gets
// the caller-supplied `nextId`. `vendor` and `model` (device class) come from
// the discover response.
//
// spec: { vendor_device_id, label, x, y, height_m, device_type, vendor }
export function upsertVendorAnchor(anchors, spec, nextId) {
  const list = anchors || [];
  const idx = list.findIndex((a) => a.vendor_device_id === spec.vendor_device_id);
  if (idx >= 0) {
    const updated = [...list];
    const prev = updated[idx];
    updated[idx] = {
      ...prev,
      x: spec.x,
      y: spec.y,
      height_m: spec.height_m,
      // Keep existing values when a later sync omits a field.
      label: spec.label || prev.label,
      vendor: spec.vendor || prev.vendor,
      model: spec.device_type || prev.model,
    };
    return updated;
  }
  return [
    ...list,
    {
      id: nextId,
      technology: "wittra",
      x: spec.x,
      y: spec.y,
      height_m: spec.height_m,
      label: spec.label,
      vendor_device_id: spec.vendor_device_id,
      vendor: spec.vendor || "",
      model: spec.device_type || "",
    },
  ];
}
