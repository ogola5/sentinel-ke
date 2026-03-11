from __future__ import annotations

import json

from app.ledger.db import SessionLocal
from app.legal.bundle_seed import seed_evidence_bundles_once


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Seed legal evidence bundles for active campaigns")
    parser.add_argument("--exported-by", default="legal-bundle-worker")
    parser.add_argument("--include-stix", action="store_true", default=True)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        out = seed_evidence_bundles_once(
            db=db,
            exported_by=args.exported_by,
            include_stix=bool(args.include_stix),
            limit=max(1, int(args.limit)),
        )
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()
