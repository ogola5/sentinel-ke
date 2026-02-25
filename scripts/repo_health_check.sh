#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[health] starting repository checks"

# 1) ensure .env is not tracked
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "[health][fail] .env is tracked by git"
  exit 1
fi

echo "[health][ok] .env is not tracked"

# 2) quick secret pattern scan in tracked text files
secret_hits=0
while IFS= read -r file; do
  [[ -f "$file" ]] || continue
  if [[ "$file" == "scripts/repo_health_check.sh" ]]; then
    continue
  fi
  case "$file" in
    *.png|*.jpg|*.jpeg|*.gif|*.svg|*.ico|*.pdf|*.zip|*.tar|*.gz|*.bin|*.pyc|*.ipynb)
      continue
      ;;
  esac
  if rg -n --no-heading --fixed-strings \
    -e "dev-secret-key" \
    -e "sentinel-notebook-token" \
    -e "minioadmin" \
    "$file" >/dev/null 2>&1; then
    echo "[health][warn] suspicious default token in $file"
    secret_hits=$((secret_hits + 1))
  fi
done < <(git ls-files)

if [[ "$secret_hits" -gt 0 ]]; then
  echo "[health][fail] found $secret_hits suspicious token/default occurrences"
  exit 1
fi

echo "[health][ok] no suspicious token/default literals found"

# 3) check for oversized tracked files (> 600 KB)
oversized=0
while IFS= read -r file; do
  [[ -f "$file" ]] || continue
  size_bytes=$(wc -c <"$file")
  if [[ "$size_bytes" -gt 614400 ]]; then
    echo "[health][warn] oversized tracked file: $file (${size_bytes} bytes)"
    oversized=$((oversized + 1))
  fi
done < <(git ls-files)

if [[ "$oversized" -gt 0 ]]; then
  echo "[health][fail] found $oversized oversized tracked files"
  exit 1
fi

echo "[health][ok] no oversized tracked files"

# 4) basic maintainability counters
test_count=$(find backend/tests -maxdepth 1 -name 'test_*.py' | wc -l | tr -d ' ')
backend_py_count=$(find backend/app -name '*.py' | wc -l | tr -d ' ')

echo "[health][info] tests=$test_count backend_py_files=$backend_py_count"
if [[ "$test_count" -lt 25 ]]; then
  echo "[health][fail] expected at least 25 backend tests"
  exit 1
fi

echo "[health][ok] test inventory threshold satisfied"

# 5) syntax check (no dependency install)
export PYTHONPYCACHEPREFIX=/tmp/pycache
python3 -m compileall -q backend/app backend/tests

echo "[health][ok] python syntax check passed"
echo "[health] all checks passed"
