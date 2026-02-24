from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import ThreatIntelIndicator, ThreatIntelSyncLog
from app.ledger.db import SessionLocal


PATTERN_RE = re.compile(r"\[(?P<kind>[a-z0-9\-]+):value\s*=\s*'(?P<value>[^']+)'\]", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_indicator(ind: Dict[str, Any]) -> Dict[str, Any] | None:
    pattern = str(ind.get("pattern") or "")
    m = PATTERN_RE.search(pattern)
    if not m:
        return None
    kind = str(m.group("kind")).lower()
    value = str(m.group("value")).strip()
    if not kind or not value:
        return None
    valid_from = ind.get("valid_from")
    valid_until = ind.get("valid_until")
    conf_raw = float(ind.get("confidence") or 0.5)
    confidence = conf_raw / 100.0 if conf_raw > 1.0 else conf_raw
    return {
        "stix_id": str(ind.get("id") or "") or None,
        "indicator_type": kind,
        "value": value,
        "confidence": max(0.0, min(1.0, confidence)),
        "tags_json": list(ind.get("labels") or []),
        "valid_from": datetime.fromisoformat(valid_from.replace("Z", "+00:00")) if valid_from else None,
        "valid_until": datetime.fromisoformat(valid_until.replace("Z", "+00:00")) if valid_until else None,
        "metadata_json": {
            "name": ind.get("name"),
            "description": ind.get("description"),
        },
    }


def import_stix_bundle(
    *,
    db: Session,
    bundle: Dict[str, Any],
    source: str = "stix",
) -> Dict[str, Any]:
    started = _now()
    sync_id = str(uuid.uuid4())
    rows = []
    for obj in list(bundle.get("objects") or []):
        if str(obj.get("type") or "") != "indicator":
            continue
        parsed = _parse_indicator(obj)
        if not parsed:
            continue
        rows.append(
            {
                "indicator_id": str(uuid.uuid4()),
                "source": source,
                **parsed,
            }
        )

    upserted = 0
    status = "ok"
    detail = None
    try:
        if rows:
            stmt = insert(ThreatIntelIndicator).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["indicator_type", "value"],
                set_={
                    "stix_id": stmt.excluded.stix_id,
                    "confidence": stmt.excluded.confidence,
                    "source": stmt.excluded.source,
                    "valid_from": stmt.excluded.valid_from,
                    "valid_until": stmt.excluded.valid_until,
                    "tags_json": stmt.excluded.tags_json,
                    "metadata_json": stmt.excluded.metadata_json,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            res = db.execute(stmt)
            upserted = int(res.rowcount or 0)
    except Exception as exc:
        status = "failed"
        detail = str(exc)

    db.add(
        ThreatIntelSyncLog(
            sync_id=sync_id,
            direction="import",
            connector=source,
            status=status,
            detail=detail,
            item_count=upserted,
            started_at=started,
            finished_at=_now(),
            metadata_json={"bundle_id": bundle.get("id")},
        )
    )
    db.commit()

    return {
        "sync_id": sync_id,
        "status": status,
        "items": upserted,
    }


def export_stix_bundle(*, db: Session, source: str = "sentinel", limit: int = 200) -> Dict[str, Any]:
    started = _now()
    sync_id = str(uuid.uuid4())

    rows = (
        db.query(ThreatIntelIndicator)
        .order_by(ThreatIntelIndicator.updated_at.desc())
        .limit(max(1, int(limit)))
        .all()
    )

    objects: List[Dict[str, Any]] = []
    for r in rows:
        pattern = f"[{r.indicator_type}:value = '{r.value}']"
        objects.append(
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": r.stix_id or f"indicator--{uuid.uuid4()}",
                "created": r.created_at.isoformat(),
                "modified": r.updated_at.isoformat(),
                "name": f"{r.indicator_type}:{r.value}",
                "pattern": pattern,
                "pattern_type": "stix",
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                "labels": list(r.tags_json or []),
                "confidence": int(max(0, min(100, float(r.confidence or 0.5) * 100))),
                "description": str((r.metadata_json or {}).get("description") or ""),
            }
        )

    bundle = {
        "type": "bundle",
        "id": f"bundle--{uuid.uuid4()}",
        "objects": objects,
    }

    db.add(
        ThreatIntelSyncLog(
            sync_id=sync_id,
            direction="export",
            connector=source,
            status="ok",
            detail=None,
            item_count=len(objects),
            started_at=started,
            finished_at=_now(),
            metadata_json={"bundle_id": bundle["id"]},
        )
    )
    db.commit()

    return {
        "sync_id": sync_id,
        "bundle": bundle,
        "items": len(objects),
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["import", "export"], default="export")
    p.add_argument("--source", default="stix")
    p.add_argument("--bundle-json", default=None)
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.mode == "import":
            if not args.bundle_json:
                raise SystemExit("--bundle-json required in import mode")
            bundle = json.loads(args.bundle_json)
            out = import_stix_bundle(db=db, bundle=bundle, source=args.source)
        else:
            out = export_stix_bundle(db=db, source=args.source)
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()
