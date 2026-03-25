#!/bin/sh
# =============================================================================
# check_training_env.sh — local GNN/ML preflight
#
# Prints a practical summary of the local machine and warns about settings that
# commonly make training/inference unusable on developer hardware.
#
# Exit codes:
#   0  environment is usable
#   1  hard failure (missing torch, unwritable artifact dir, or --strict warn)
# =============================================================================
set -eu

STRICT=0
if [ "${1:-}" = "--strict" ]; then
  STRICT=1
fi

warn_count=0

warn() {
  printf '%s\n' "WARN: $*" >&2
  warn_count=$((warn_count + 1))
}

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
ARTIFACT_DIR="${GNN_ARTIFACT_DIR:-$ROOT_DIR/artifacts/gnn}"

printf '%s\n' "Sentinel-KE GNN runtime preflight"
printf '%s\n' "root_dir=$ROOT_DIR"
printf '%s\n' "artifact_dir=$ARTIFACT_DIR"

export GNN_ARTIFACT_DIR="$ARTIFACT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  else
    fail "python or python3 is not available on PATH"
  fi
fi

if ! "$PYTHON_BIN" - <<'PY'
import os
import platform
import shutil
import subprocess
import sys

print(f"python={platform.python_version()}")
try:
    import torch  # type: ignore
except Exception as exc:  # pragma: no cover - runtime diagnostic
    print(f"torch=missing ({exc.__class__.__name__}: {exc})")
    sys.exit(1)

cuda_available = torch.cuda.is_available()
print(f"torch={torch.__version__}")
print(f"cuda_available={str(cuda_available).lower()}")
if cuda_available:
    print(f"cuda_devices={torch.cuda.device_count()}")
    for idx in range(torch.cuda.device_count()):
        try:
            props = torch.cuda.get_device_properties(idx)
            total_gb = props.total_memory / (1024 ** 3)
            print(f"gpu[{idx}]={props.name} vram_gb={total_gb:.1f}")
        except Exception as exc:  # pragma: no cover - runtime diagnostic
            print(f"gpu[{idx}]=unavailable ({exc.__class__.__name__})")
else:
    print("gpu=none")

def mem_total_gb() -> float | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = float(line.split()[1])
                    return kb / (1024 ** 2)
    except Exception:
        return None
    return None

mem_gb = mem_total_gb()
if mem_gb is not None:
    print(f"host_ram_gb={mem_gb:.1f}")
else:
    print("host_ram_gb=unknown")

free = shutil.which("free")
if free:
    try:
        out = subprocess.check_output([free, "-h"], text=True)
        print("free_output_begin")
        print(out.rstrip())
        print("free_output_end")
    except Exception:
        pass

artifact_dir = os.environ.get("GNN_ARTIFACT_DIR") or os.path.join(os.getcwd(), "artifacts", "gnn")
os.makedirs(artifact_dir, exist_ok=True)
probe = os.path.join(artifact_dir, ".write_test")
with open(probe, "w", encoding="utf-8") as fh:
    fh.write("ok\n")
os.remove(probe)
print(f"artifact_dir_writable=true")
PY
then
  fail "torch import or CUDA preflight failed"
fi

if [ -z "${DATABASE_URL:-}" ]; then
  warn "DATABASE_URL is unset; training workers will not be able to connect to Postgres"
fi

if [ -z "${REDPANDA_BROKERS:-}" ]; then
  warn "REDPANDA_BROKERS is unset; inference consumers may not start"
fi

if [ -z "${CUBLAS_WORKSPACE_CONFIG:-}" ]; then
  warn "CUBLAS_WORKSPACE_CONFIG is unset; CUDA determinism will be relaxed"
fi

CPU_THREADS="${GNN_CPU_THREADS:-4}"
MAX_ENTITIES="${GNN_MAX_ENTITIES:-2500}"
MAX_EDGES="${GNN_MAX_EDGES:-20000}"
EPOCHS="${GNN_EPOCHS:-30}"
PRETRAIN_EPOCHS="${GNN_PRETRAIN_EPOCHS:-3}"
WINDOW_KEY="${GNN_WINDOW_KEY:-Wmid}"
INFER_BATCH_THRESHOLD="${INFERENCE_BATCH_THRESHOLD:-25}"
INFER_MIN_INTERVAL="${INFERENCE_MIN_INTERVAL_SEC:-30}"

printf '%s\n' "settings:"
printf '%s\n' "  GNN_CPU_THREADS=$CPU_THREADS"
printf '%s\n' "  GNN_MAX_ENTITIES=$MAX_ENTITIES"
printf '%s\n' "  GNN_MAX_EDGES=$MAX_EDGES"
printf '%s\n' "  GNN_EPOCHS=$EPOCHS"
printf '%s\n' "  GNN_PRETRAIN_EPOCHS=$PRETRAIN_EPOCHS"
printf '%s\n' "  GNN_WINDOW_KEY=$WINDOW_KEY"
printf '%s\n' "  INFERENCE_BATCH_THRESHOLD=$INFER_BATCH_THRESHOLD"
printf '%s\n' "  INFERENCE_MIN_INTERVAL_SEC=$INFER_MIN_INTERVAL"

if [ "$CPU_THREADS" -lt 2 ] 2>/dev/null; then
  warn "GNN_CPU_THREADS is very low; training will be slower than necessary"
fi

if [ "$MAX_ENTITIES" -gt 5000 ] 2>/dev/null; then
  warn "GNN_MAX_ENTITIES is high for local hardware; expect long training and high RAM use"
fi

if [ "$MAX_EDGES" -gt 50000 ] 2>/dev/null; then
  warn "GNN_MAX_EDGES is high for local hardware; edge tensor build may dominate runtime"
fi

if [ "$EPOCHS" -gt 40 ] 2>/dev/null; then
  warn "GNN_EPOCHS is high for local iteration; consider 20-30 on CPU or 30-40 on GPU"
fi

if [ "$PRETRAIN_EPOCHS" -gt 5 ] 2>/dev/null; then
  warn "GNN_PRETRAIN_EPOCHS is high for local iteration"
fi

if [ "$WINDOW_KEY" = "Wshort" ]; then
  warn "GNN_WINDOW_KEY=Wshort is the freshest slice and is often sparse; use Wmid for more stable local runs"
fi

if [ "$INFER_BATCH_THRESHOLD" -gt 50 ] 2>/dev/null; then
  warn "INFERENCE_BATCH_THRESHOLD is high; inference will feel sluggish locally"
fi

if [ "$INFER_MIN_INTERVAL" -gt 60 ] 2>/dev/null; then
  warn "INFERENCE_MIN_INTERVAL_SEC is high; inference cadence may lag behind fresh events"
fi

if [ -r /proc/meminfo ]; then
  MEM_KB="$(awk '/MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)"
  if [ "${MEM_KB:-0}" -gt 0 ]; then
    if [ "$MEM_KB" -lt 16000000 ] 2>/dev/null; then
      warn "host RAM is below 16 GB; CPU training will likely be slow and memory pressure will be high"
    elif [ "$MEM_KB" -lt 32000000 ] 2>/dev/null && [ "$MAX_ENTITIES" -gt 2500 ] 2>/dev/null; then
      warn "host RAM is below 32 GB while graph size is above the local default; expect swapping or OOM risk"
    fi
  fi
fi

if [ "$STRICT" -eq 1 ] && [ "$warn_count" -gt 0 ]; then
  fail "strict mode failed with $warn_count warning(s)"
fi

printf '%s\n' "preflight_status=ok"
