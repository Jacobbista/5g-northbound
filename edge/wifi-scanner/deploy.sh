#!/usr/bin/env bash
# Deploy / sync the WiFi scanner to a Raspberry Pi.
#
#   ./deploy.sh [code|config|service|all]   (default: all)
#
# Configuration is read from ./.env (copy from .env.example). The .env file is
# gitignored - real targets and asset ids never enter the repository.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "!! $ENV_FILE not found. Copy .env.example to .env and fill in." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${PI_HOST:?PI_HOST not set in .env}"
: "${ADAPTER_URL:?ADAPTER_URL not set in .env}"
: "${DEVICE_ID:?DEVICE_ID not set in .env}"
INTERFACE="${INTERFACE:-wlan0}"
SEND_INTERVAL="${SEND_INTERVAL:-1.0}"

for v in PI_HOST ADAPTER_URL DEVICE_ID; do
  if [[ "${!v}" == *CHANGE-ME* ]]; then
    echo "!! $v still has the placeholder value '${!v}' - edit $ENV_FILE" >&2
    exit 1
  fi
done

code=false config=false unit=false
case "${1:-all}" in
  code)    code=true ;;
  config)  config=true ;;
  service) unit=true ;;
  all|"")  code=true; config=true; unit=true ;;
  *) echo "usage: $0 [code|config|service|all]"; exit 1 ;;
esac

echo "→ target: $PI_HOST  asset: $DEVICE_ID  adapter: $ADAPTER_URL"

if $code; then
  echo "→ sync scanner.py"
  scp "$HERE/scanner.py" "$PI_HOST:/home/pi/scanner.py"
fi

if $unit; then
  echo "→ sync scanner.service"
  scp "$HERE/scanner.service" "$PI_HOST:/tmp/scanner.service"
  ssh "$PI_HOST" 'sudo mv /tmp/scanner.service /etc/systemd/system/scanner.service && sudo systemctl daemon-reload'
fi

if $config; then
  echo "→ write /etc/positioning-scanner.env"
  ssh "$PI_HOST" "sudo tee /etc/positioning-scanner.env >/dev/null" <<EOF
ADAPTER_URL=$ADAPTER_URL
DEVICE_ID=$DEVICE_ID
INTERFACE=$INTERFACE
SEND_INTERVAL=$SEND_INTERVAL
EOF
fi

echo "→ enable + restart scanner"
ssh "$PI_HOST" 'sudo systemctl enable scanner >/dev/null 2>&1 || true; sudo systemctl restart scanner; sleep 1; systemctl --no-pager status scanner | head -5'
echo "✓ done - watch with:  ssh $PI_HOST journalctl -u scanner -f"
