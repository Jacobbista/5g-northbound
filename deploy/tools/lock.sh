#!/usr/bin/env bash
# Lock what goes into the images. Run the tests afterwards. Invoked by
# `make lock`.
#
# 1. Pin every base image (`FROM name:tag`) of services/ and mocks/ to the
#    digest the tag points at now.
# 2. Regenerate services/<service>/constraints.txt for every Python image:
#    install the declared dependencies in the pinned python base into a
#    separate prefix, as the Dockerfile does, and pin every package installed
#    there. Packages of the base image itself come with its digest.
set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

dockerfiles=(services/*/Dockerfile mocks/*/Dockerfile)

# Resolve every digest before rewriting any Dockerfile, so a failed lookup
# leaves them untouched. A build stage (`FROM builder`) and `scratch` are not
# registry images.
stages=$(sed -nE 's/^FROM .* AS ([^ ]+).*$/\1/ip' "${dockerfiles[@]}" | sort -u)
declare -A digests
for ref in $(sed -nE 's/^FROM ([^ @]+)(@sha256:[0-9a-f]+)?( .*)?$/\1/p' "${dockerfiles[@]}" | sort -u); do
  if [ "$ref" = scratch ] || grep -qxF "$ref" <<<"$stages"; then continue; fi
  digest=$(docker buildx imagetools inspect "$ref" | awk '/^Digest:/ && !d {d = $2} END {print d}')
  [ -n "$digest" ] || { echo "no digest for $ref" >&2; exit 1; }
  digests[$ref]=$digest
done
for ref in "${!digests[@]}"; do
  sed -i -E "s#^FROM ${ref}(@sha256:[0-9a-f]+)?( |\$)#FROM ${ref}@${digests[$ref]}\\2#" "${dockerfiles[@]}"
  echo "  $ref@${digests[$ref]}"
done

python=$(sed -nE 's/^FROM (python:[^ ]+).*/\1/p' services/camara-gateway/Dockerfile | head -1)
for dir in services/*/; do
  dir=${dir%/}
  grep -q "pip install" "$dir/Dockerfile" 2>/dev/null || continue
  service=$(basename "$dir")
  if [ -f "$dir/pyproject.toml" ]; then install="pip install -q --prefix=/install ."; else install="pip install -q --prefix=/install -r requirements.txt"; fi
  echo "  $service"
  pins=$(docker run --rm -v "$PWD/$dir:/src:ro" "$python" sh -c "
    mkdir /tmp/s && tar -C /src --exclude=.venv --exclude=node_modules -cf - . | tar -C /tmp/s -xf - &&
    cd /tmp/s && $install >&2 &&
    pip freeze --path /install/lib/python3.11/site-packages" | grep -E '^[A-Za-z0-9._-]+==')
  { echo "# Every package the image installs, pinned. \`make lock\` regenerates it."; echo "$pins"; } > "$dir/constraints.txt"
  echo "    $(echo "$pins" | wc -l) packages"
done
