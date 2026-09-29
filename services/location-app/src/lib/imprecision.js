// When a position counts as imprecise: its accuracy is worse than what its
// sources nominally deliver. A source's bound is its declared nominalAccuracy,
// else the upper bound of its declared accuracy_class, else the deployment
// threshold VITE_ACCURACY_MAX_M. A fused position takes the widest bound among
// its sources. The declarations come from the gateway's /adapters and the
// published accuracy-class vocabulary.

const FALLBACK_M = Number(
  (typeof window !== "undefined" && window.__ENV__?.VITE_ACCURACY_MAX_M) || 15
);

let capsBySource = {};
let classes = {};

// Record the current declarations. Called on every render of the app with the
// latest /adapters list and vocabulary, so the bounds follow the fabric.
export function setAccuracyDeclarations(adapters = [], vocabulary = null) {
  capsBySource = {};
  for (const a of adapters) {
    const caps = a?.capabilities || {};
    const source = caps.source || a?.name;
    if (source) capsBySource[source] = caps;
  }
  classes = vocabulary?.classes || {};
}

function boundForSource(source) {
  const caps = capsBySource[source] || {};
  if (Number(caps.nominalAccuracy) > 0) return Number(caps.nominalAccuracy);
  const upper = classes[caps.accuracy_class]?.upperBound;
  if (typeof upper === "number") return upper;
  return FALLBACK_M;
}

function sourcesOf(position) {
  if (position?.sources?.length) return position.sources;
  return position?.source ? [position.source] : [];
}

export function accuracyBound(position) {
  const sources = sourcesOf(position);
  if (!sources.length) return FALLBACK_M;
  return Math.max(...sources.map(boundForSource));
}

// The accuracy as the source reported it, without CAMARA's 1 m floor on the
// radius when the response carries it.
export function isImprecise(position) {
  const accuracy = position?.horizontalAccuracy ?? position?.area?.radius;
  if (accuracy == null) return false;
  return accuracy > accuracyBound(position);
}
