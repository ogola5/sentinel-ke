from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.service import IngestionService
from app.integrations.connectors import map_external_event
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.integrations.real_data")


DEFAULT_KEV_FEED_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
DEFAULT_EPSS_API_URL = "https://api.first.org/data/v1/epss"


@dataclass(frozen=True)
class NormalizedConnectorRecord:
    connector_key: str
    payload: Dict[str, Any]
    confidence: float


@dataclass(frozen=True)
class IngestionJobStats:
    total_records: int
    accepted: int
    duplicates: int
    skipped: int
    errors: int


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_iso_utc(value: Any, *, fallback_now: bool = True) -> Optional[str]:
    if value is None:
        return _utcnow_iso() if fallback_now else None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        s = str(value).strip()
        if not s:
            return _utcnow_iso() if fallback_now else None
        if s.isdigit():
            ts = float(s)
            if ts > 1e12:
                ts /= 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            normalized = s.replace("Z", "+00:00")
            parsed = None
            for fmt in (
                None,
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
            ):
                try:
                    if fmt is None:
                        parsed = datetime.fromisoformat(normalized)
                    else:
                        parsed = datetime.strptime(s, fmt)
                    break
                except Exception:
                    continue
            if parsed is None:
                return _utcnow_iso() if fallback_now else None
            dt = parsed

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (key or "").lower())


def _row_index(row: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        nk = _norm_key(str(k))
        if nk and nk not in out:
            out[nk] = v
    return out


def _pick(idx: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        nk = _norm_key(k)
        if nk in idx and idx[nk] is not None:
            return idx[nk]
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    if f is None:
        return None
    return int(f)


def _http_get_json(
    url: str,
    *,
    timeout_sec: int = 30,
    params: Optional[Mapping[str, str]] = None,
    getter: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    response = getter(url, params=params, timeout=timeout_sec)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object from {url}")
    return payload


def load_kev_rows(*, kev_file: Optional[str] = None, kev_url: str = DEFAULT_KEV_FEED_URL) -> List[Dict[str, Any]]:
    if kev_file:
        obj = json.loads(Path(kev_file).read_text(encoding="utf-8"))
    else:
        obj = _http_get_json(kev_url)
    rows = obj.get("vulnerabilities") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        raise ValueError("KEV payload missing vulnerabilities[]")
    return [r for r in rows if isinstance(r, dict)]


def fetch_epss_lookup(
    cve_ids: Sequence[str],
    *,
    epss_api_url: str = DEFAULT_EPSS_API_URL,
    timeout_sec: int = 30,
    chunk_size: int = 200,
    getter: Callable[..., Any] = requests.get,
) -> Dict[str, float]:
    clean = sorted({str(c).strip().upper() for c in cve_ids if str(c).strip()})
    if not clean:
        return {}

    out: Dict[str, float] = {}
    for i in range(0, len(clean), max(1, int(chunk_size))):
        chunk = clean[i : i + max(1, int(chunk_size))]
        raw = _http_get_json(
            epss_api_url,
            timeout_sec=timeout_sec,
            params={"cve": ",".join(chunk)},
            getter=getter,
        )
        data = raw.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            cve = str(item.get("cve") or "").strip().upper()
            epss = _as_float(item.get("epss"))
            if cve and epss is not None:
                out[cve] = max(0.0, min(1.0, float(epss)))
    return out


def _kev_severity(row: Mapping[str, Any]) -> str:
    ransomware = str(row.get("knownRansomwareCampaignUse") or "").strip().lower()
    if ransomware in {"known", "yes", "true"}:
        return "critical"
    return "high"


def build_kev_epss_records(
    kev_rows: Sequence[Mapping[str, Any]],
    *,
    asset_id: str,
    epss_lookup: Optional[Mapping[str, float]] = None,
    confidence: float = 0.95,
) -> List[NormalizedConnectorRecord]:
    epss_lookup = epss_lookup or {}
    out: List[NormalizedConnectorRecord] = []
    for row in kev_rows:
        cve = str(row.get("cveID") or row.get("cve_id") or row.get("cve") or "").strip().upper()
        if not cve:
            continue
        payload: Dict[str, Any] = {
            "published_at": _to_iso_utc(row.get("dateAdded"), fallback_now=True),
            "asset_id": asset_id,
            "cve_id": cve,
            "severity": _kev_severity(row),
            "kev": True,
            "cisa_due_date": _to_iso_utc(row.get("dueDate"), fallback_now=False),
            "status": "open",
            "vendor_project": row.get("vendorProject"),
            "product": row.get("product"),
            "vulnerability_name": row.get("vulnerabilityName"),
            "known_ransomware_use": row.get("knownRansomwareCampaignUse"),
            "notes": row.get("notes"),
        }
        epss = _as_float(epss_lookup.get(cve))
        if epss is not None:
            payload["epss"] = epss
        out.append(
            NormalizedConnectorRecord(
                connector_key="kev_vuln_feed_v1",
                payload={k: v for k, v in payload.items() if v is not None},
                confidence=confidence,
            )
        )
    return out


_CIC_DDOS_KEYWORDS = (
    "ddos",
    "dos hulk",
    "hulk",
    "goldeneye",
    "slowloris",
    "slowhttptest",
    "udp flood",
    "syn flood",
)

_CIC_WEB_KEYWORDS = (
    "web attack",
    "xss",
    "sql injection",
    "sqli",
    "brute force -web",
    "command injection",
    "path traversal",
    "lfi",
    "rfi",
    "csrf",
)


def _classify_cic_label(label: str) -> Optional[str]:
    x = (label or "").strip().lower()
    if not x or "benign" in x:
        return None
    if any(k in x for k in _CIC_DDOS_KEYWORDS):
        return "ddos"
    if any(k in x for k in _CIC_WEB_KEYWORDS):
        return "web"
    return None


def _normalize_web_attack_type(label: str) -> str:
    x = (label or "").strip().lower()
    if "sql" in x:
        return "sql_injection"
    if "xss" in x:
        return "xss"
    if "brute" in x:
        return "credential_bruteforce"
    if "path traversal" in x or "lfi" in x or "rfi" in x:
        return "path_traversal"
    if "command injection" in x:
        return "command_injection"
    return "web_attack"


def normalize_cic_row(
    row: Mapping[str, Any],
    *,
    service_id_prefix: str = "cic",
    dataset_name: str = "cic_ids2018",
) -> Optional[NormalizedConnectorRecord]:
    idx = _row_index(row)
    label = str(_pick(idx, "label", "attack_type", "class", "category") or "").strip()
    category = _classify_cic_label(label)
    if not category:
        return None

    ts = _to_iso_utc(
        _pick(
            idx,
            "timestamp",
            "flow_start_time",
            "flow start time",
            "start_time",
            "event_time",
        ),
        fallback_now=True,
    )
    src_ip = str(_pick(idx, "src_ip", "source_ip", "source", "flow_src_ip") or "").strip() or None
    dst_ip = str(_pick(idx, "dst_ip", "destination_ip", "flow_dst_ip", "target_ip") or "").strip() or None
    dst_port = _as_int(_pick(idx, "dst_port", "destination_port", "destination port", "target_port"))
    method = str(_pick(idx, "http_method", "method") or "").strip() or None
    uri = str(_pick(idx, "uri", "path", "http_uri", "request_path", "endpoint") or "").strip() or None

    if dst_ip:
        service_id = f"{service_id_prefix}:{dst_ip}"
    else:
        service_id = f"{service_id_prefix}:unknown"
    endpoint = uri or (f"port:{dst_port}" if dst_port is not None else None)

    req_rate = _as_float(
        _pick(
            idx,
            "flow_packets_s",
            "flow packets/s",
            "packets_per_second",
            "pkt_rate",
            "request_rate",
            "rps",
        )
    )
    packet_count = _as_int(
        _pick(
            idx,
            "total_fwd_packets",
            "tot_fwd_pkts",
            "fwd_packet_count",
            "packet_count",
            "requests",
            "req_count",
        )
    )
    if req_rate is None and packet_count is not None:
        req_rate = float(packet_count)

    if category == "ddos":
        payload = {
            "timestamp": ts,
            "service_id": service_id,
            "endpoint": endpoint,
            "method": method,
            "request_rate": req_rate,
            "error_rate": _as_float(_pick(idx, "error_rate", "packet_loss_ratio", "loss_ratio")),
            "unique_ips_count": _as_int(_pick(idx, "unique_src_ips", "src_ip_count")) or (1 if src_ip else None),
            "latency_ms": _as_float(_pick(idx, "latency_ms", "flow_iat_mean", "flowiatmean")),
            "endpoint_convergence": _as_float(_pick(idx, "endpoint_convergence")),
            "asn_concentration": _as_float(_pick(idx, "asn_concentration")),
            "dataset": dataset_name,
            "attack_label": label,
        }
        return NormalizedConnectorRecord(
            connector_key="cloudflare_ddos_v1",
            payload={k: v for k, v in payload.items() if v is not None},
            confidence=0.9,
        )

    payload = {
        "timestamp": ts,
        "service_id": service_id,
        "endpoint": endpoint,
        "attack_type": _normalize_web_attack_type(label),
        "status": "detected",
        "src_ip": src_ip,
        "method": method,
        "req_count": packet_count,
        "dataset": dataset_name,
        "attack_label": label,
    }
    return NormalizedConnectorRecord(
        connector_key="waf_api_attack_v1",
        payload={k: v for k, v in payload.items() if v is not None},
        confidence=0.88,
    )


def normalize_caida_row(
    row: Mapping[str, Any],
    *,
    service_id_prefix: str = "caida",
    dataset_name: str = "caida_ddos",
) -> Optional[NormalizedConnectorRecord]:
    idx = _row_index(row)
    ts = _to_iso_utc(
        _pick(idx, "timestamp", "time", "window_end", "event_time", "ts"),
        fallback_now=True,
    )
    target = str(_pick(idx, "service_id", "target_service", "target_ip", "dst_ip") or "").strip() or "unknown"
    service_id = f"{service_id_prefix}:{target}"
    target_port = _as_int(_pick(idx, "target_port", "dst_port", "destination_port"))
    endpoint = str(_pick(idx, "endpoint", "path", "uri") or "").strip() or None
    if not endpoint and target_port is not None:
        endpoint = f"port:{target_port}"

    req_rate = _as_float(_pick(idx, "pps", "packets_per_second", "packet_rate", "request_rate", "rps"))
    unique_ips = _as_int(_pick(idx, "unique_src_ips", "attacker_count", "src_ip_count"))
    if unique_ips is None:
        unique_ips = _as_int(_pick(idx, "flows", "flow_count"))

    payload = {
        "timestamp": ts,
        "service_id": service_id,
        "endpoint": endpoint,
        "method": str(_pick(idx, "protocol", "method") or "").strip() or None,
        "request_rate": req_rate,
        "error_rate": _as_float(_pick(idx, "drop_rate", "loss_ratio", "error_rate")),
        "unique_ips_count": unique_ips,
        "latency_ms": _as_float(_pick(idx, "latency_ms", "rtt_ms")),
        "dataset": dataset_name,
        "attack_label": str(_pick(idx, "label", "attack_type", "class") or "ddos").strip(),
    }
    return NormalizedConnectorRecord(
        connector_key="cloudflare_ddos_v1",
        payload={k: v for k, v in payload.items() if v is not None},
        confidence=0.94,
    )


def iter_rows_from_path(path: str) -> Iterator[Dict[str, Any]]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row:
                    yield dict(row)
        return
    if suffix in {".jsonl", ".ndjson"}:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if isinstance(obj, dict):
                    yield obj
        return

    obj = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(obj, dict):
        for key in ("items", "records", "data", "rows", "vulnerabilities"):
            values = obj.get(key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        yield item
                return
    raise ValueError(f"unsupported file format or structure: {path}")


def ingest_records_via_connectors(
    *,
    db: Session,
    records: Iterable[NormalizedConnectorRecord],
    source_api_key: str,
    classification: Optional[str] = "RESTRICTED",
) -> IngestionJobStats:
    svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
    total = accepted = duplicates = skipped = errors = 0

    for record in records:
        total += 1
        try:
            event = map_external_event(
                connector_key=record.connector_key,
                payload=record.payload,
                confidence=record.confidence,
                classification=classification,
            )
            result = svc.ingest_event(event=event, source_api_key=source_api_key)
            if result.status == "accepted":
                accepted += 1
            elif result.status == "duplicate":
                duplicates += 1
            else:
                skipped += 1
        except Exception as exc:
            errors += 1
            log.exception(
                "real_data_ingest_failed connector=%s err=%s payload=%s",
                record.connector_key,
                exc,
                record.payload,
            )

    return IngestionJobStats(
        total_records=total,
        accepted=accepted,
        duplicates=duplicates,
        skipped=skipped,
        errors=errors,
    )


def _run_kev_epss_job(args: argparse.Namespace) -> IngestionJobStats:
    kev_rows = load_kev_rows(kev_file=args.kev_file, kev_url=args.kev_url)
    cves = [str(row.get("cveID") or row.get("cve") or "").strip().upper() for row in kev_rows]
    epss_lookup = {}
    if not args.skip_epss:
        try:
            epss_lookup = fetch_epss_lookup(cves, epss_api_url=args.epss_url, timeout_sec=args.timeout_sec)
        except Exception as exc:
            log.warning("epss_lookup_failed err=%s", exc)
    records = build_kev_epss_records(
        kev_rows,
        asset_id=args.asset_id,
        epss_lookup=epss_lookup,
        confidence=args.confidence,
    )
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
        )
    finally:
        db.close()


def _iter_cic_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    service_id_prefix: str,
    dataset_name: str,
) -> Iterator[NormalizedConnectorRecord]:
    for row in rows:
        record = normalize_cic_row(row, service_id_prefix=service_id_prefix, dataset_name=dataset_name)
        if record is not None:
            yield record


def _iter_caida_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    service_id_prefix: str,
    dataset_name: str,
) -> Iterator[NormalizedConnectorRecord]:
    for row in rows:
        record = normalize_caida_row(row, service_id_prefix=service_id_prefix, dataset_name=dataset_name)
        if record is not None:
            yield record


def _run_traffic_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = iter_rows_from_path(args.input_file)
    if args.dataset == "cic":
        records = _iter_cic_records(
            rows,
            service_id_prefix=args.service_id_prefix,
            dataset_name=args.dataset_name or "cic_ids2018",
        )
    else:
        records = _iter_caida_records(
            rows,
            service_id_prefix=args.service_id_prefix,
            dataset_name=args.dataset_name or "caida_ddos",
        )

    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
        )
    finally:
        db.close()


def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ingest real-world cyber datasets via existing Sentinel connector flow.",
    )
    p.add_argument("--source-api-key", required=True, help="SourceRegistry API key used for ingestion auth.")
    p.add_argument("--classification", default="RESTRICTED", help="Classification for mapped events.")
    p.add_argument("--confidence", type=float, default=0.92, help="Default confidence for generated events.")

    sub = p.add_subparsers(dest="job", required=True)

    p_kev = sub.add_parser("kev-epss", help="Import CISA KEV and enrich with FIRST EPSS.")
    p_kev.add_argument("--asset-id", required=True, help="Target asset/service id to attach KEV rows to.")
    p_kev.add_argument("--kev-file", default=None, help="Path to KEV JSON file. If omitted, feed URL is used.")
    p_kev.add_argument("--kev-url", default=DEFAULT_KEV_FEED_URL, help="KEV feed URL.")
    p_kev.add_argument("--epss-url", default=DEFAULT_EPSS_API_URL, help="FIRST EPSS API URL.")
    p_kev.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout for remote feed calls.")
    p_kev.add_argument("--skip-epss", action="store_true", help="Skip EPSS enrichment lookup.")

    p_traffic = sub.add_parser("traffic", help="Normalize CIC/CAIDA traffic rows into DDoS/Web events.")
    p_traffic.add_argument("--dataset", choices=("cic", "caida"), required=True, help="Traffic dataset family.")
    p_traffic.add_argument("--input-file", required=True, help="Input path (.csv/.json/.jsonl).")
    p_traffic.add_argument("--service-id-prefix", default="external", help="Service id prefix for mapped rows.")
    p_traffic.add_argument("--dataset-name", default=None, help="Optional dataset tag written into payload.")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.job == "kev-epss":
        stats = _run_kev_epss_job(args)
    else:
        stats = _run_traffic_job(args)

    print(
        json.dumps(
            {
                "job": args.job,
                "total_records": stats.total_records,
                "accepted": stats.accepted,
                "duplicates": stats.duplicates,
                "skipped": stats.skipped,
                "errors": stats.errors,
            }
        )
    )
    return 0 if stats.errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
