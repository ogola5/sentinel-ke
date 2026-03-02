from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.normalizers import normalize_event
from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService
from app.ingestion.validators import validate_event
from app.ledger.db import SessionLocal


@dataclass(frozen=True)
class ReplayStats:
    rows_loaded: int
    skipped_invalid: int
    total_events: int
    sent: int
    accepted_2xx: int
    rejected_non_2xx: int
    failures: int
    duration_seconds: float
    rps_effective: float
    latency_p50_ms: Optional[float]
    latency_p95_ms: Optional[float]
    latency_p99_ms: Optional[float]
    status_counts: Dict[str, int] = field(default_factory=dict)
    error_samples: List[str] = field(default_factory=list)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("empty_datetime")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _percentile(values: Sequence[float], p: int) -> Optional[float]:
    if not values:
        return None
    arr = sorted(float(v) for v in values)
    idx = min(len(arr) - 1, int(len(arr) * (float(p) / 100.0)))
    return round(arr[idx], 3)


def _load_event_rows(
    db: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    section_code: Optional[str],
    event_types: Sequence[str],
    limit: int,
) -> List[Dict[str, Any]]:
    filters = [
        "occurred_at >= :start_at",
        "occurred_at <= :end_at",
    ]
    params: Dict[str, Any] = {
        "start_at": start_at,
        "end_at": end_at,
        "limit": max(1, int(limit)),
    }
    if section_code:
        filters.append("section_code = :section_code")
        params["section_code"] = str(section_code)
    if event_types:
        filters.append("event_type = ANY(:event_types)")
        params["event_types"] = [str(x) for x in event_types]

    rows = db.execute(
        text(
            f"""
            SELECT
                event_hash,
                event_type,
                occurred_at,
                classification,
                schema_version,
                anchors_json,
                payload_json
            FROM event_log
            WHERE {' AND '.join(filters)}
            ORDER BY occurred_at ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def _to_canonical_event(row: Mapping[str, Any], *, shift_to_now: bool) -> Dict[str, Any]:
    occurred = row.get("occurred_at")
    if isinstance(occurred, datetime):
        occurred_iso = occurred.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    else:
        occurred_iso = _iso_now()
    if shift_to_now:
        occurred_iso = _iso_now()

    return {
        "event_type": str(row.get("event_type") or ""),
        "occurred_at": occurred_iso,
        "confidence": 0.9,
        "classification": str(row.get("classification") or "RESTRICTED"),
        "schema_version": str(row.get("schema_version") or "v1"),
        "anchors": dict(row.get("anchors_json") or {}),
        "payload": dict(row.get("payload_json") or {}),
    }


def _post_event(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    event: Mapping[str, Any],
    timeout_sec: int,
) -> Tuple[bool, int, float, Optional[str]]:
    t0 = time.perf_counter()
    try:
        resp = session.post(
            f"{base_url.rstrip('/')}/v1/ingest/event",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            json=dict(event),
            timeout=max(1, int(timeout_sec)),
        )
        elapsed = (time.perf_counter() - t0) * 1000.0
        return (200 <= resp.status_code < 300), int(resp.status_code), float(elapsed), None
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - t0) * 1000.0
        return False, 0, float(elapsed), str(exc)


def _post_event_direct(
    *,
    source_api_key: str,
    event: Mapping[str, Any],
) -> Tuple[bool, int, float, Optional[str]]:
    t0 = time.perf_counter()
    db = SessionLocal()
    try:
        canonical = CanonicalEvent.model_validate(dict(event))
        svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
        res = svc.ingest_event(event=canonical, source_api_key=source_api_key)
        elapsed = (time.perf_counter() - t0) * 1000.0
        # accepted/duplicate are both successful replay outcomes.
        return True, 200 if res.status == "accepted" else 208, float(elapsed), None
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - t0) * 1000.0
        return False, 0, float(elapsed), str(exc)
    finally:
        db.close()


def replay_events(
    *,
    rows: Sequence[Mapping[str, Any]],
    base_url: str,
    api_key: str,
    mode: str = "direct",
    concurrency: int = 10,
    timeout_sec: int = 15,
    rate_per_sec: float = 0.0,
    shift_to_now: bool = True,
) -> ReplayStats:
    rows_loaded = len(rows)
    skipped_invalid = 0
    skip_samples: List[str] = []
    events: List[Dict[str, Any]] = []
    for row in rows:
        ev = _to_canonical_event(row, shift_to_now=shift_to_now)
        try:
            parsed = CanonicalEvent.model_validate(ev)
            normalized = normalize_event(parsed)
            validate_event(normalized)
            events.append(normalized.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            skipped_invalid += 1
            if len(skip_samples) < 5:
                skip_samples.append(str(exc))
    total = len(events)
    if total <= 0:
        return ReplayStats(
            rows_loaded=rows_loaded,
            skipped_invalid=skipped_invalid,
            total_events=0,
            sent=0,
            accepted_2xx=0,
            rejected_non_2xx=0,
            failures=0,
            duration_seconds=0.0,
            rps_effective=0.0,
            latency_p50_ms=None,
            latency_p95_ms=None,
            latency_p99_ms=None,
            status_counts={},
            error_samples=skip_samples,
        )

    sent = accepted = rejected = failures = 0
    latencies: List[float] = []
    status_counts: Dict[str, int] = {}
    error_samples: List[str] = []
    started = time.perf_counter()

    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
            futures = []
            next_slot = time.perf_counter()
            for ev in events:
                if rate_per_sec > 0:
                    now = time.perf_counter()
                    if now < next_slot:
                        time.sleep(next_slot - now)
                    next_slot = max(next_slot, now) + (1.0 / float(rate_per_sec))
                if str(mode).lower() == "http":
                    futures.append(
                        pool.submit(
                            _post_event,
                            session=session,
                            base_url=base_url,
                            api_key=api_key,
                            event=ev,
                            timeout_sec=timeout_sec,
                        )
                    )
                else:
                    futures.append(
                        pool.submit(
                            _post_event_direct,
                            source_api_key=api_key,
                            event=ev,
                        )
                    )

            for fut in as_completed(futures):
                ok, status, elapsed_ms, err = fut.result()
                sent += 1
                latencies.append(float(elapsed_ms))
                bucket = str(int(status or 0))
                status_counts[bucket] = status_counts.get(bucket, 0) + 1
                if err:
                    failures += 1
                    if len(error_samples) < 5:
                        error_samples.append(str(err))
                    continue
                if ok:
                    accepted += 1
                else:
                    rejected += 1

    duration = max(0.0001, time.perf_counter() - started)
    return ReplayStats(
        rows_loaded=rows_loaded,
        skipped_invalid=skipped_invalid,
        total_events=total,
        sent=sent,
        accepted_2xx=accepted,
        rejected_non_2xx=rejected,
        failures=failures,
        duration_seconds=round(duration, 4),
        rps_effective=round(float(sent / duration), 4),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_p99_ms=_percentile(latencies, 99),
        status_counts=status_counts,
        error_samples=(skip_samples + error_samples)[:5],
    )


def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Replay historical incident events into /v1/ingest/event under controlled load.")
    p.add_argument("--mode", choices=("direct", "http"), default="direct", help="Replay mode.")
    p.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    p.add_argument(
        "--api-key",
        required=True,
        help="For direct mode: SourceRegistry raw API key. For http mode: API key expected by /v1/ingest/event guard.",
    )
    p.add_argument("--start-at", required=True, help="Replay window start (ISO8601).")
    p.add_argument("--end-at", required=True, help="Replay window end (ISO8601).")
    p.add_argument("--section-code", default=None, help="Optional section filter.")
    p.add_argument("--event-type", action="append", default=[], help="Filter event type (repeatable).")
    p.add_argument("--limit", type=int, default=500, help="Max events to replay.")
    p.add_argument("--concurrency", type=int, default=10, help="Worker threads for replay.")
    p.add_argument("--rate-per-sec", type=float, default=0.0, help="Optional send-rate cap (0 = unlimited).")
    p.add_argument("--timeout-sec", type=int, default=15, help="HTTP timeout per request.")
    p.add_argument("--keep-original-time", action="store_true", help="Do not rewrite occurred_at to now().")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_cli().parse_args(argv)

    start_at = _parse_iso(args.start_at)
    end_at = _parse_iso(args.end_at)
    db = SessionLocal()
    try:
        rows = _load_event_rows(
            db,
            start_at=start_at,
            end_at=end_at,
            section_code=args.section_code,
            event_types=list(args.event_type or []),
            limit=max(1, int(args.limit)),
        )
    finally:
        db.close()

    stats = replay_events(
        rows=rows,
        base_url=args.base_url,
        api_key=args.api_key,
        mode=args.mode,
        concurrency=max(1, int(args.concurrency)),
        timeout_sec=max(1, int(args.timeout_sec)),
        rate_per_sec=max(0.0, float(args.rate_per_sec)),
        shift_to_now=not bool(args.keep_original_time),
    )
    print(json.dumps(stats.__dict__, default=str))
    return 0 if (stats.failures == 0 and stats.rejected_non_2xx == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())
