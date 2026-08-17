#!/bin/sh
# Render /usr/share/nginx/html/env-config.js from environment variables.
# Dropped into /docker-entrypoint.d/ by the Dockerfile so the stock
# nginx:alpine entrypoint runs it before launching nginx. A k8s Secret
# rotation only needs a pod restart - no image rebuild.
ENV_FILE="/usr/share/nginx/html/env-config.js"

# In compose the file is bind-mounted read-only from the repo so the operator
# can hot-edit it without rebuilding. Honour that: try-write and skip on any
# error. POSIX `-w` does not always reflect bind-mount :ro on alpine/busybox,
# hence the explicit `touch` probe.
if ! (touch "$ENV_FILE" 2>/dev/null); then
  echo "env-config.js is not writable (bind-mount?); skipping regeneration"
  exit 0
fi

cat > "$ENV_FILE" <<EOF
window.__ENV__ = {
  VITE_CAMARA_API_BASE: "${VITE_CAMARA_API_BASE:-http://localhost:8087}",
  VITE_KEYCLOAK_URL: "${VITE_KEYCLOAK_URL:-http://localhost:8180}",
  VITE_KEYCLOAK_REALM: "${VITE_KEYCLOAK_REALM:-5g-testbed}",
  VITE_KEYCLOAK_CLIENT_ID: "${VITE_KEYCLOAK_CLIENT_ID:-location-app}",
  VITE_GPS_ORIGIN_LAT: "${VITE_GPS_ORIGIN_LAT:-45.064312}",
  VITE_GPS_ORIGIN_LON: "${VITE_GPS_ORIGIN_LON:-7.659154}",
  VITE_FLOOR_W: "${VITE_FLOOR_W:-13}",
  VITE_FLOOR_D: "${VITE_FLOOR_D:-32}",
  VITE_ACCURACY_MAX_M: "${VITE_ACCURACY_MAX_M:-15}",
};
EOF
