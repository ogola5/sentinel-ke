from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import WorkerHeartbeat


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def mark_worker_started(
    db: Session,
    *,
    worker_name: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        now = _utcnow()
        stmt = insert(WorkerHeartbeat).values(
            worker_name=str(worker_name),
            last_started_at=now,
            last_status="running",
            last_detail=None,
            metadata_json=dict(metadata or {}),
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["worker_name"],
            set_={
                "last_started_at": stmt.excluded.last_started_at,
                "last_status": stmt.excluded.last_status,
                "last_detail": stmt.excluded.last_detail,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        db.execute(stmt)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def mark_worker_finished(
    db: Session,
    *,
    worker_name: str,
    status: str,
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        now = _utcnow()
        stmt = insert(WorkerHeartbeat).values(
            worker_name=str(worker_name),
            last_finished_at=now,
            last_status=str(status or "unknown"),
            last_detail=(str(detail)[:500] if detail else None),
            metadata_json=dict(metadata or {}),
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["worker_name"],
            set_={
                "last_finished_at": stmt.excluded.last_finished_at,
                "last_status": stmt.excluded.last_status,
                "last_detail": stmt.excluded.last_detail,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        db.execute(stmt)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def summarize_worker_freshness(
    db: Session,
    *,
    worker_names: Sequence[str] | None = None,
    warn_after_minutes: int = 15,
    fail_after_minutes: int = 60,
) -> list[dict[str, Any]]:
    try:
        q = db.query(WorkerHeartbeat)
        if worker_names:
            q = q.filter(WorkerHeartbeat.worker_name.in_(list(worker_names)))
        rows = q.order_by(WorkerHeartbeat.worker_name.asc()).all()
    except Exception:  # noqa: BLE001
        return []
    now = _utcnow()
    out: list[dict[str, Any]] = []
    for row in rows:
        reference = row.last_finished_at or row.last_started_at
        age_minutes = None
        if reference:
            age_minutes = max(0.0, (now - reference).total_seconds() / 60.0)

        freshness = "fail"
        if str(row.last_status or "").lower() == "running":
            freshness = "warn"
        elif age_minutes is None:
            freshness = "fail"
        elif age_minutes >= max(1, int(fail_after_minutes)):
            freshness = "fail"
        elif age_minutes >= max(1, int(warn_after_minutes)):
            freshness = "warn"
        else:
            freshness = "pass"

        out.append(
            {
                "worker_name": row.worker_name,
                "last_status": row.last_status,
                "last_detail": row.last_detail,
                "last_started_at": row.last_started_at.isoformat() if row.last_started_at else None,
                "last_finished_at": row.last_finished_at.isoformat() if row.last_finished_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "age_minutes": round(age_minutes, 2) if age_minutes is not None else None,
                "freshness": freshness,
                "metadata": dict(row.metadata_json or {}),
            }
        )
    seen = {str(item.get("worker_name") or "") for item in out}
    for worker_name in worker_names or []:
        name = str(worker_name or "")
        if not name or name in seen:
            continue
        out.append(
            {
                "worker_name": name,
                "last_status": "missing",
                "last_detail": "No heartbeat recorded.",
                "last_started_at": None,
                "last_finished_at": None,
                "updated_at": None,
                "age_minutes": None,
                "freshness": "fail",
                "metadata": {},
            }
        )
    out.sort(key=lambda x: str(x.get("worker_name") or ""))
    return out
