#!/bin/bash
# Sentinel-KE — Full training run (all 3 lanes)
# Usage: bash scripts/run_training_all_lanes.sh [--epochs N] [--window-key KEY]
#
# Prerequisites:
#   - DATABASE_URL set in environment
#   - PaySim CSV at $PAYSIM_CSV (optional — Lane 2 is skipped when unset)
#   - Run from the backend/ directory, or this script will cd there automatically
#
# Optional env overrides:
#   TRAINING_EPOCHS      epochs for Lane 1 & Lane 3   (default: 60)
#   GNN_WINDOW_KEY       window key for Lane 1          (default: Wmid)
#   PAYSIM_WINDOW_KEY    window key for Lane 2          (default: Wpaysim)
#   CORRUPTION_WINDOW    window key for Lane 3          (default: Wcorruption)
#   GNN_ARTIFACT_DIR     where to save .pt artifacts   (default: /app/artifacts/gnn)

set -e
cd "$(dirname "$0")/.."

EPOCHS="${TRAINING_EPOCHS:-60}"
CYBER_WINDOW="${GNN_WINDOW_KEY:-Wmid}"
PAYSIM_WINDOW="${PAYSIM_WINDOW_KEY:-Wpaysim}"
CORRUPTION_WINDOW="${CORRUPTION_WINDOW:-Wcorruption}"

# Load training overrides if the file exists
if [ -f ".env.training" ]; then
  echo "[run_training_all_lanes] Loading .env.training overrides"
  # shellcheck source=/dev/null
  set -a; . .env.training; set +a
fi

echo ""
echo "============================================================"
echo " Sentinel-KE — Full GNN training run"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo " epochs=${EPOCHS}  cyber_window=${CYBER_WINDOW}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Lane 1: Cyber GNN (Wmid)
# ---------------------------------------------------------------------------
echo "=== Lane 1: Cyber GNN (window=${CYBER_WINDOW}) ==="
python -m app.analytics.layer3.gnn_train_worker \
  --window-key "${CYBER_WINDOW}" \
  --prediction-type risk_gnn \
  --epochs "${EPOCHS}"

echo ""
echo "Lane 1 complete."
echo ""

# ---------------------------------------------------------------------------
# Lane 2: Fraud GNN (PaySim) — optional
# ---------------------------------------------------------------------------
echo "=== Lane 2: Fraud GNN (PaySim) ==="
if [ -n "${PAYSIM_CSV:-}" ]; then
  python scripts/run_paysim_gnn.py \
    --csv "${PAYSIM_CSV}" \
    --window-key "${PAYSIM_WINDOW}"
  echo ""
  echo "Lane 2 complete."
else
  echo "PAYSIM_CSV not set — skipping fraud benchmark lane."
  echo "  To run: export PAYSIM_CSV=/path/to/PS_*.csv && bash scripts/run_training_all_lanes.sh"
fi
echo ""

# ---------------------------------------------------------------------------
# Lane 3: Corruption GNN
# ---------------------------------------------------------------------------
echo "=== Lane 3: Corruption GNN (window=${CORRUPTION_WINDOW}) ==="
python -m app.analytics.corruption.train_worker \
  --allow-demo-fairness-override \
  --window-key "${CORRUPTION_WINDOW}"

echo ""
echo "Lane 3 complete."
echo ""

echo "============================================================"
echo " All lanes complete — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"
