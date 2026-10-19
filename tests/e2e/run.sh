#!/usr/bin/env bash
# Web 版の通し E2E を Playwright のコンテナで走らせる (AI の API はモック  外へは CDN だけ)
# 使い方: bash tests/e2e/run.sh   要るもの: Docker
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
IMAGE=mcr.microsoft.com/playwright:v1.55.0-noble
docker run --rm --init --ipc=host \
  -v "$REPO":/repo:ro -v "$HERE":/e2e -w /e2e \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 -e REPO=/repo \
  "$IMAGE" bash -c '
    set -e
    [ -d node_modules/playwright ] || npm install --no-save --no-audit --no-fund --silent playwright@1.55.0 >/dev/null
    rm -f shots/*.png
    node e2e.mjs'
