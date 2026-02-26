#!/bin/sh
# =============================================================================
# render_startup.sh — Sentinel-KE Web Service startup (Render.com)
# =============================================================================
set -e

# ---------------------------------------------------------------------------
# 1. Fix Render's DATABASE_URL for psycopg2
#    Render injects:  postgresql://user:pass@host/db
#    psycopg2 needs:  postgresql+psycopg2://user:pass@host/db
# ---------------------------------------------------------------------------
if echo "$DATABASE_URL" | grep -q "^postgresql://"; then
  export DATABASE_URL="postgresql+psycopg2://${DATABASE_URL#postgresql://}"
  echo "[startup] Patched DATABASE_URL driver prefix"
fi

# ---------------------------------------------------------------------------
# 2. Wait for PostgreSQL to be ready (Render may start DB after web service)
# ---------------------------------------------------------------------------
echo "[startup] Waiting for PostgreSQL..."
python - <<'PYEOF'
import os, time, sys
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
engine = create_engine(url, pool_pre_ping=True)

for attempt in range(30):
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        print(f"[startup] PostgreSQL ready (attempt {attempt + 1})")
        sys.exit(0)
    except Exception as exc:
        print(f"[startup] DB not ready yet ({exc}), retry {attempt + 1}/30...")
        time.sleep(3)

print("[startup] ERROR: PostgreSQL not reachable after 90s — aborting")
sys.exit(1)
PYEOF

# ---------------------------------------------------------------------------
# 3. Apply any pending one-time schema patches
#    (same fixes that were applied manually in dev)
# ---------------------------------------------------------------------------
echo "[startup] Applying schema patches..."
python - <<'PYEOF'
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])

patches = [
    # ai_prediction missing columns
    """ALTER TABLE ai_prediction
         ADD COLUMN IF NOT EXISTS model_version    VARCHAR NOT NULL DEFAULT 'unknown',
         ADD COLUMN IF NOT EXISTS confidence       FLOAT   NOT NULL DEFAULT 0.0,
         ADD COLUMN IF NOT EXISTS uncertainty      FLOAT   NOT NULL DEFAULT 1.0,
         ADD COLUMN IF NOT EXISTS abstained        BOOLEAN NOT NULL DEFAULT false,
         ADD COLUMN IF NOT EXISTS kill_chain_stage VARCHAR,
         ADD COLUMN IF NOT EXISTS decision_source  VARCHAR NOT NULL DEFAULT 'heuristic'""",

    # ai_explanation missing columns
    """ALTER TABLE ai_explanation
         ADD COLUMN IF NOT EXISTS recommended_controls_json JSONB NOT NULL DEFAULT '[]'::jsonb,
         ADD COLUMN IF NOT EXISTS counterfactual_json       JSONB NOT NULL DEFAULT '{}'::jsonb""",

    # ai_risk_threshold missing column
    """ALTER TABLE ai_risk_threshold
         ADD COLUMN IF NOT EXISTS cost_weight FLOAT NOT NULL DEFAULT 1.0""",

    # infra_cluster missing cluster_key
    """ALTER TABLE infra_cluster
         ADD COLUMN IF NOT EXISTS cluster_key TEXT""",
    """UPDATE infra_cluster
         SET cluster_key = concat('legacy:', cluster_id::text)
         WHERE COALESCE(cluster_key, '') = ''""",
    """CREATE UNIQUE INDEX IF NOT EXISTS ux_infra_cluster_cluster_key
         ON infra_cluster (cluster_key)""",
]

with engine.begin() as conn:
    for patch in patches:
        try:
            conn.execute(text(patch))
        except Exception as exc:
            # Non-fatal: table may not exist yet (DB_AUTO_CREATE will handle it)
            print(f"[startup] patch skipped ({exc.__class__.__name__}): {patch[:60]}...")

print("[startup] Schema patches applied")
PYEOF

# ---------------------------------------------------------------------------
# 4. Start the web server
#    - 2 uvicorn workers for concurrency (free tier has 0.5 CPU)
#    - 120s timeout for long GNN queries
# ---------------------------------------------------------------------------
echo "[startup] Starting Sentinel-KE API on port ${PORT:-8000}..."
exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile -
