// What a source can do, from what its adapter advertises to the engine's
// registry (GET /adapters, proxied by the gateway). The app asks a source only
// for what it has declared, rather than trying and reading the refusal.

// The sources whose adapter advertises `capability`.
export function sourcesAdvertising(adapters = [], capability) {
  return new Set(
    adapters
      .filter((a) => a?.capabilities?.[capability])
      .map((a) => a.capabilities?.source || a.name)
      .filter(Boolean)
  );
}
