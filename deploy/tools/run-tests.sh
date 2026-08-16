#!/usr/bin/env bash
# Run every service's test suite and print a single pass/fail roundup at the end.
# A failing suite dumps its output inline; the script exits non-zero if any fail.
# Invoked by `make test`.
set -uo pipefail
cd "$(dirname "$0")/../.."  # repo root

# name | working directory | command
suites=(
  "camara-gateway|services/camara-gateway|.venv/bin/pytest -q"
  "positioning-engine|services/positioning-engine|.venv/bin/pytest -q"
  "wifi-positioning|services/wifi-positioning|.venv/bin/pytest -q"
  "placement-editor|services/placement-editor|.venv/bin/pytest -q"
  "rest-adapter|services/rest-adapter|.venv/bin/pytest -q"
  "mock-positioning|mocks/mock-positioning|.venv/bin/pytest -q"
  "mock-wittra|mocks/mock-wittra|.venv/bin/pytest -q"
  "positioning-demo (js)|.|npm --prefix services/positioning-demo test"
  "placement-editor (js)|.|npm --prefix services/placement-editor/frontend test"
  "profile overlays|.|python3 deploy/tools/apply_overlay.py services/camara-gateway/spec/location-retrieval.yaml spec/private-profile/overlay-retrieval.yaml /tmp/_r.yaml && python3 deploy/tools/apply_overlay.py services/camara-gateway/spec/location-verification.yaml spec/private-profile/overlay-verification.yaml /tmp/_v.yaml && echo '2 overlays applied'"
)

log=$(mktemp -d)
declare -a results
fails=0

for entry in "${suites[@]}"; do
  IFS='|' read -r name dir cmd <<<"$entry"
  out="$log/${name// /_}.log"
  if ( cd "$dir" && eval "$cmd" ) >"$out" 2>&1; then
    summary=$(grep -hE '[0-9]+ passed' "$out" | tail -1 | sed 's/^[[:space:]]*//')
    printf '  \033[32m✓\033[0m %-22s %s\n' "$name" "$summary"
    results+=("ok|$name|$summary")
  else
    printf '  \033[31m✗ %-22s FAILED\033[0m\n' "$name"
    echo "----- $name output -----"; cat "$out"; echo "------------------------"
    results+=("fail|$name|")
    fails=$((fails + 1))
  fi
done

total=${#suites[@]}
echo ""
echo "  ── test summary ──────────────────────────────"
for r in "${results[@]}"; do
  IFS='|' read -r st name summary <<<"$r"
  if [ "$st" = ok ]; then printf '  ✓ %-22s %s\n' "$name" "$summary"
  else printf '  ✗ %-22s FAILED\n' "$name"; fi
done
echo "  ──────────────────────────────────────────────"
rm -rf "$log"
if [ "$fails" -eq 0 ]; then
  printf '  \033[32mALL GREEN\033[0m - %d/%d suites passed\n\n' "$total" "$total"
else
  printf '  \033[31m%d/%d suites FAILED\033[0m (output above)\n\n' "$fails" "$total"
  exit 1
fi
