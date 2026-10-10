#!/usr/bin/env bash
# Build the deployable images locally to catch what only the deploy's build
# would: a JSX syntax error, a missing dependency, a bad Dockerfile.
#
#   scripts/test-build.sh            # webapp api bot
#   scripts/test-build.sh webapp     # just one
#
# Meant for the Claude Code cloud sandbox, where the Docker daemon is not
# running by default and builds reach the network only through the sandbox
# proxy: it starts `dockerd` if needed and builds with `--network host`,
# forwarding $HTTPS_PROXY. On a normal machine with a running daemon and no
# proxy it is just three `docker build`s.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
  echo "starting dockerd..."
  nohup dockerd >"${TMPDIR:-/tmp}/dockerd.log" 2>&1 &

  for _ in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done

  docker info >/dev/null 2>&1 || { echo "dockerd did not start"; exit 1; }
fi

proxy_args=()

if [ -n "${HTTPS_PROXY:-}" ]; then
  proxy_args=(--network host --build-arg "HTTPS_PROXY=$HTTPS_PROXY" --build-arg "HTTP_PROXY=$HTTPS_PROXY")
fi

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(webapp api bot)

for target in "${targets[@]}"; do
  echo "==> building $target"
  docker build "${proxy_args[@]}" -f "Dockerfile.$target" -t "daily-notes-$target:test" .
done

echo "all builds succeeded: ${targets[*]}"
