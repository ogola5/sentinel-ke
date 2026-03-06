#!/bin/sh
set -eu

LOCKFILE="package-lock.json"
STAMP_FILE="node_modules/.sentinel-lock.sha256"

current_hash=""
stored_hash=""

if [ -f "$LOCKFILE" ]; then
  current_hash="$(sha256sum "$LOCKFILE" | awk '{print $1}')"
fi

if [ -f "$STAMP_FILE" ]; then
  stored_hash="$(cat "$STAMP_FILE" || true)"
fi

need_install=0

if [ ! -d "node_modules" ]; then
  need_install=1
fi

if [ ! -d "node_modules/lucide-react" ]; then
  need_install=1
fi

if [ -n "$current_hash" ] && [ "$current_hash" != "$stored_hash" ]; then
  need_install=1
fi

if [ "$need_install" -eq 1 ]; then
  echo "[frontend] Installing dependencies from package-lock.json ..."
  npm ci --prefer-offline
  mkdir -p node_modules
  if [ -n "$current_hash" ]; then
    echo "$current_hash" > "$STAMP_FILE"
  fi
fi

exec npm run dev -- --host 0.0.0.0
