// Scene-label display shortener. Long device ids (a Wittra hardware id is 17
// chars) overrun the 3D floating labels. Past `max` chars, keep the last
// `keep` - the trailing digits are what distinguish one unit from another -
// behind a leading ellipsis. Short ids (AP01) pass through unchanged.
export function shortLabel(value, { max = 12, keep = 6 } = {}) {
  const s = value == null ? "" : String(value);
  if (s.length <= max) return s;
  return `…${s.slice(-keep)}`;
}
