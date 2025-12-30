from datetime import datetime, timedelta, timezone
from app.ledger.db import SessionLocal
from app.analytics.layer3.infra_reuse_worker import run_infra_reuse_claims

db = SessionLocal()

now = datetime.now(timezone.utc)

created = run_infra_reuse_claims(
    db=db,
    window_key="24h",
    window_start=now - timedelta(hours=24),
    window_end=now,
)

db.commit()
db.close()

print(f"claims_created={created}")
