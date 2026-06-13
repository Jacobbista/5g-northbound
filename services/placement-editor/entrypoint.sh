#!/bin/sh
# Generate /app/static/env-config.js from environment variables at container
# start so the frontend can read runtime configuration (e.g. a Mapbox token
# supplied via a k8s Secret) without rebuilding the JS bundle. Values default
# to empty strings so the file is always well-formed.
ENV_FILE="/app/static/env-config.js"

# In compose the file is bind-mounted read-only from the repo so the operator
# can hot-edit it. Skip regeneration when not writable (POSIX `-w` does not
# always reflect bind-mount :ro on some kernels, hence the explicit touch
# probe).
if ! (touch "$ENV_FILE" 2>/dev/null); then
  echo "env-config.js is not writable (bind-mount?); skipping regeneration"
  exec "$@"
fi

cat > "$ENV_FILE" <<EOF
window.__ENV__ = {
  VITE_MAPBOX_TOKEN: "${VITE_MAPBOX_TOKEN:-}",
  VITE_MAP_TILE_URL: "${VITE_MAP_TILE_URL:-}",
};
EOF

exec "$@"
