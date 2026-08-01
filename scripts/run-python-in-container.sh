#!/bin/sh
set -eu

image="classroom-downloader:test"
docker build -t "$image" .
exec docker run --rm \
  -e PYTHONPATH=/workspace/tests:/workspace \
  -v "$(pwd):/workspace" \
  -w /workspace \
  "$image" python "$@"
