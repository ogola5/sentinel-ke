from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import requests
from sqlalchemy.orm import Session

from app.analytics.layer3.threat_intel_worker import import_stix_bundle
from app.core.config import settings
from app.ingestion.service import IngestionService
from app.integrations.connectors import map_external_event
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.integrations.real_data")


DEFAULT_KEV_FEED_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
DEFAULT_EPSS_API_URL = "https://api.first.org/data/v1/epss"
DEFAULT_FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.json"
DEFAULT_URLHAUS_CSV_URL = "https://urlhaus.abuse.ch/downloads/csv_online/"
DEFAULT_THREATFOX_URL = "https://threatfox.abuse.ch/export/json/recent/"
DEFAULT_MALWAREBAZAAR_URL = "https://mb-api.abuse.ch/api/v1/"
DEFAULT_OTX_SUBSCRIBED_URL = "https://otx.alienvault.com/api/v1/pulses/subscribed"


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
    headers: Optional[Mapping[str, str]] = None,
    getter: Callable[..., Any] = requests.get,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"params": params, "timeout": timeout_sec}
    if headers:
        kwargs["headers"] = headers
    response = getter(url, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object from {url}")
    return payload


def _http_get_any_json(
    url: str,
    *,
    timeout_sec: int = 30,
    params: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    getter: Callable[..., Any] = requests.get,
) -> Any:
    kwargs: Dict[str, Any] = {"params": params, "timeout": timeout_sec}
    if headers:
        kwargs["headers"] = headers
    response = getter(url, **kwargs)
    response.raise_for_status()
    return response.json()


def _http_get_text(
    url: str,
    *,
    timeout_sec: int = 30,
    params: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    getter: Callable[..., Any] = requests.get,
) -> str:
    kwargs: Dict[str, Any] = {"params": params, "timeout": timeout_sec}
    if headers:
        kwargs["headers"] = headers
    response = getter(url, **kwargs)
    response.raise_for_status()
    return str(getattr(response, "text", ""))


def _http_post_any_json(
    url: str,
    *,
    timeout_sec: int = 30,
    data: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    getter: Callable[..., Any] = requests.post,
) -> Any:
    kwargs: Dict[str, Any] = {"data": data, "timeout": timeout_sec}
    if headers:
        kwargs["headers"] = headers
    response = getter(url, **kwargs)
    response.raise_for_status()
    return response.json()


def _iter_csv_rows_from_text(raw: str) -> Iterator[Dict[str, Any]]:
    lines = [line for line in str(raw or "").splitlines() if line and not line.startswith("#")]
    if not lines:
        return
    reader = csv.DictReader(lines)
    for row in reader:
        if row:
            yield dict(row)


def _extract_domain(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = urlsplit(str(value).strip())
    except Exception:
        return None
    host = (parsed.hostname or "").strip().lower()
    return host or None


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


def load_feodo_rows(
    *,
    feodo_file: Optional[str] = None,
    feodo_url: str = DEFAULT_FEODO_URL,
    timeout_sec: int = 30,
    getter: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    if feodo_file:
        path = Path(feodo_file)
        if path.suffix.lower() == ".csv":
            return list(iter_rows_from_path(str(path)))
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = _http_get_any_json(feodo_url, timeout_sec=timeout_sec, getter=getter)

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("items") or payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError("Feodo payload missing row list")


def build_feodo_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    confidence: float = 0.96,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    for row in rows:
        idx = _row_index(row)
        ip = str(_pick(idx, "ip_address", "ip", "host") or "").strip()
        if not ip:
            continue
        payload: Dict[str, Any] = {
            "timestamp": _utcnow_iso(),
            "first_seen_utc": _to_iso_utc(
                _pick(idx, "first_seen_utc", "first_seen", "first_seen_at", "last_online"),
                fallback_now=True,
            ),
            "ip_address": ip,
            "malware": _pick(idx, "malware", "malware_family", "family"),
            "status": _pick(idx, "status", "online_status"),
            "port": _as_int(_pick(idx, "port", "dst_port", "c2_port")),
            "reporter": _pick(idx, "reporter", "reporter_name"),
        }
        out.append(
            NormalizedConnectorRecord(
                connector_key="feodo_c2_v1",
                payload={k: v for k, v in payload.items() if v is not None},
                confidence=confidence,
            )
        )
    return out


def load_urlhaus_rows(
    *,
    urlhaus_file: Optional[str] = None,
    urlhaus_url: str = DEFAULT_URLHAUS_CSV_URL,
    auth_key: Optional[str] = None,
    timeout_sec: int = 30,
    getter: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    if urlhaus_file:
        path = Path(urlhaus_file)
        if path.suffix.lower() == ".csv":
            return list(_iter_csv_rows_from_text(path.read_text(encoding="utf-8")))
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("urls") or payload.get("data") or payload.get("items")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        raise ValueError("URLhaus file payload missing row list")

    key = (auth_key or os.environ.get("URLHAUS_AUTH_KEY") or "").strip()
    if not key:
        raise ValueError("URLhaus auth key required for live URLhaus downloads")
    text = _http_get_text(
        urlhaus_url,
        timeout_sec=timeout_sec,
        params={"auth-key": key},
        getter=getter,
    )
    return list(_iter_csv_rows_from_text(text))


def build_urlhaus_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    confidence: float = 0.94,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    for row in rows:
        idx = _row_index(row)
        url = str(_pick(idx, "url", "indicator", "ioc") or "").strip()
        if not url:
            continue
        host = str(_pick(idx, "host", "domain", "hostname") or "").strip() or _extract_domain(url)
        payload: Dict[str, Any] = {
            "timestamp": _utcnow_iso(),
            "date_added": _to_iso_utc(
                _pick(idx, "dateadded", "date_added", "timestamp", "firstseen"),
                fallback_now=True,
            ),
            "url": url,
            "host": host,
            "host_ip": _pick(idx, "host_ip", "ip", "ip_address"),
            "threat": _pick(idx, "threat", "threat_type", "classification"),
            "url_status": _pick(idx, "url_status", "status"),
            "tags": _pick(idx, "tags", "tag"),
            "reporter": _pick(idx, "reporter", "reporter_name"),
            "id": _pick(idx, "id", "urlhaus_id"),
        }
        out.append(
            NormalizedConnectorRecord(
                connector_key="urlhaus_ioc_v1",
                payload={k: v for k, v in payload.items() if v is not None},
                confidence=confidence,
            )
        )
    return out


def load_threatfox_rows(
    *,
    threatfox_file: Optional[str] = None,
    threatfox_url: str = DEFAULT_THREATFOX_URL,
    timeout_sec: int = 30,
    getter: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    if threatfox_file:
        path = Path(threatfox_file)
        if path.suffix.lower() == ".csv":
            return list(iter_rows_from_path(str(path)))
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = _http_get_any_json(threatfox_url, timeout_sec=timeout_sec, getter=getter)

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("items") or payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError("ThreatFox payload missing row list")


def build_threatfox_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    confidence: float = 0.94,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    for row in rows:
        idx = _row_index(row)
        indicator = str(_pick(idx, "ioc", "indicator", "value") or "").strip()
        indicator_type = str(_pick(idx, "ioc_type", "indicator_type", "type") or "").strip().lower()
        if not indicator or not indicator_type:
            continue
        payload: Dict[str, Any] = {
            "timestamp": _to_iso_utc(_pick(idx, "first_seen", "date_added", "created"), fallback_now=True),
            "indicator": indicator,
            "indicator_type": indicator_type,
            "malware": _pick(idx, "malware", "malware_printable", "threat_type"),
            "status": _pick(idx, "status", "ioc_status") or "active",
            "tags": _pick(idx, "tags", "tag"),
            "reporter": _pick(idx, "reporter", "reporter_name"),
            "id": _pick(idx, "id", "ioc_id", "threatfox_id"),
        }
        out.append(
            NormalizedConnectorRecord(
                connector_key="threatfox_ioc_v1",
                payload={k: v for k, v in payload.items() if v is not None},
                confidence=confidence,
            )
        )
    return out


def load_malwarebazaar_rows(
    *,
    malwarebazaar_file: Optional[str] = None,
    malwarebazaar_url: str = DEFAULT_MALWAREBAZAAR_URL,
    timeout_sec: int = 30,
    getter: Callable[..., Any] = requests.post,
) -> List[Dict[str, Any]]:
    if malwarebazaar_file:
        path = Path(malwarebazaar_file)
        if path.suffix.lower() == ".csv":
            return list(iter_rows_from_path(str(path)))
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = _http_post_any_json(
            malwarebazaar_url,
            timeout_sec=timeout_sec,
            data={"query": "get_recent"},
            getter=getter,
        )

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("items") or payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError("MalwareBazaar payload missing row list")


def build_malwarebazaar_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    confidence: float = 0.95,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    for row in rows:
        idx = _row_index(row)
        sha256 = str(_pick(idx, "sha256_hash", "sha256", "hash") or "").strip().lower()
        if not sha256:
            continue
        payload: Dict[str, Any] = {
            "timestamp": _to_iso_utc(_pick(idx, "first_seen", "date_added", "file_added"), fallback_now=True),
            "sha256_hash": sha256,
            "malware_family": _pick(idx, "signature", "malware_family", "family"),
            "file_name": _pick(idx, "file_name", "filename"),
            "file_type": _pick(idx, "file_type", "filetype"),
            "file_type_mime": _pick(idx, "file_type_mime", "mime_type"),
            "delivery_url": _pick(idx, "delivery_url", "url"),
            "tags": _pick(idx, "tags", "tag"),
            "status": _pick(idx, "status", "sample_status") or "active",
            "sample_id": _pick(idx, "sample_id", "id"),
            "reporter": _pick(idx, "reporter", "reporter_name"),
        }
        out.append(
            NormalizedConnectorRecord(
                connector_key="malwarebazaar_sample_v1",
                payload={k: v for k, v in payload.items() if v is not None},
                confidence=confidence,
            )
        )
    return out


def load_otx_pulses(
    *,
    otx_file: Optional[str] = None,
    api_key: Optional[str] = None,
    otx_url: str = DEFAULT_OTX_SUBSCRIBED_URL,
    timeout_sec: int = 30,
    limit: int = 100,
    modified_since: Optional[str] = None,
    getter: Callable[..., Any] = requests.get,
) -> List[Dict[str, Any]]:
    if otx_file:
        payload = json.loads(Path(otx_file).read_text(encoding="utf-8"))
    else:
        key = (api_key or os.environ.get("OTX_API_KEY") or "").strip()
        if not key:
            raise ValueError("OTX API key required for live OTX fetch")
        headers = {"X-OTX-API-KEY": key}
        params: Dict[str, str] = {"limit": str(max(1, int(limit)))}
        if modified_since:
            params["modified_since"] = modified_since
        payload = _http_get_any_json(
            otx_url,
            timeout_sec=timeout_sec,
            params=params,
            headers=headers,
            getter=getter,
        )

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("pulses") or payload.get("items")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError("OTX payload missing pulses/results list")


def _otx_indicator_kind(indicator_type: str) -> Optional[str]:
    x = (indicator_type or "").strip().lower()
    if x in {"ipv4", "ipv4-addr", "ip", "ipv6", "ipv6-addr"}:
        return "ip"
    if x in {"domain", "hostname"}:
        return "domain"
    if x == "url":
        return "url"
    return None


def build_otx_indicator_records(
    pulses: Sequence[Mapping[str, Any]],
    *,
    confidence: float = 0.93,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    for pulse in pulses:
        pulse_name = str(pulse.get("name") or pulse.get("title") or "alienvault_otx").strip()
        pulse_id = str(pulse.get("id") or pulse.get("pulse_id") or "").strip() or None
        tags = pulse.get("tags") or []
        indicators = pulse.get("indicators") if isinstance(pulse.get("indicators"), list) else []
        for ind in indicators:
            if not isinstance(ind, dict):
                continue
            kind = _otx_indicator_kind(str(ind.get("type") or ""))
            value = str(ind.get("indicator") or ind.get("value") or "").strip()
            if not kind or not value:
                continue
            payload: Dict[str, Any] = {
                "timestamp": _utcnow_iso(),
                "indicator": value,
                "indicator_type": kind,
                "pulse_name": pulse_name,
                "pulse_id": pulse_id,
                "indicator_id": ind.get("id"),
                "first_seen": _to_iso_utc(ind.get("created") or pulse.get("modified") or pulse.get("created")),
                "status": ind.get("is_active") if ind.get("is_active") is not None else "active",
                "tags": tags,
                "severity": "high",
            }
            out.append(
                NormalizedConnectorRecord(
                    connector_key="otx_indicator_v1",
                    payload={k: v for k, v in payload.items() if v is not None},
                    confidence=confidence,
                )
            )
    return out


def build_otx_stix_bundle(
    pulses: Sequence[Mapping[str, Any]],
    *,
    default_confidence: int = 80,
) -> Dict[str, Any]:
    objects: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for pulse in pulses:
        tags = [str(tag).strip() for tag in list(pulse.get("tags") or []) if str(tag).strip()]
        indicators = pulse.get("indicators") if isinstance(pulse.get("indicators"), list) else []
        created = _to_iso_utc(pulse.get("created") or pulse.get("modified"), fallback_now=True)
        modified = _to_iso_utc(pulse.get("modified") or pulse.get("created"), fallback_now=True)
        for ind in indicators:
            if not isinstance(ind, dict):
                continue
            raw_type = str(ind.get("type") or "").strip().lower()
            value = str(ind.get("indicator") or ind.get("value") or "").strip()
            if not value:
                continue
            if raw_type in {"ipv4", "ip", "ipv4-addr"}:
                pattern = f"[ipv4-addr:value = '{value}']"
            elif raw_type in {"ipv6", "ipv6-addr"}:
                pattern = f"[ipv6-addr:value = '{value}']"
            elif raw_type in {"domain", "hostname"}:
                pattern = f"[domain-name:value = '{value.lower()}']"
            elif raw_type == "url":
                pattern = f"[url:value = '{value}']"
            else:
                continue

            key = (raw_type, value.lower())
            if key in seen:
                continue
            seen.add(key)

            objects.append(
                {
                    "type": "indicator",
                    "spec_version": "2.1",
                    "id": f"indicator--{uuid.uuid4()}",
                    "created": _to_iso_utc(ind.get("created") or created, fallback_now=True),
                    "modified": _to_iso_utc(ind.get("modified") or modified, fallback_now=True),
                    "pattern_type": "stix",
                    "pattern": pattern,
                    "valid_from": _to_iso_utc(ind.get("created") or created, fallback_now=True),
                    "labels": tags or ["otx"],
                    "confidence": int(ind.get("confidence") or default_confidence),
                }
            )

    return {
        "type": "bundle",
        "id": f"bundle--{uuid.uuid4()}",
        "objects": objects,
    }


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
    if not x:
        return None
    if "benign" in x:
        return "benign"
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
            "benchmark_family": "ddos",
            "ground_truth_label": True,
        }
        return NormalizedConnectorRecord(
            connector_key="cloudflare_ddos_v1",
            payload={k: v for k, v in payload.items() if v is not None},
            confidence=0.9,
        )
    if category == "benign":
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
            "benchmark_family": "ddos",
            "confirmed_benign": True,
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
        "benchmark_family": "web_attack",
        "ground_truth_label": True,
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
        "benchmark_family": "ddos",
        "ground_truth_label": True,
    }
    return NormalizedConnectorRecord(
        connector_key="cloudflare_ddos_v1",
        payload={k: v for k, v in payload.items() if v is not None},
        confidence=0.94,
    )


def normalize_vpn_benchmark_row(
    row: Mapping[str, Any],
    *,
    dataset_name: str = "iscx_vpn2016",
    confidence: float = 0.88,
) -> Optional[NormalizedConnectorRecord]:
    idx = _row_index(row)
    label = str(_pick(idx, "label", "category", "traffic_type", "class") or "").strip().lower()
    app_label = str(_pick(idx, "app_label", "application", "app", "service") or "").strip()
    vpn_flag = str(_pick(idx, "vpn", "is_vpn", "vpn_label") or "").strip().lower()
    label_tokens = set(label.replace("-", " ").replace("_", " ").split())
    compact_label = label.replace("-", "").replace("_", "").replace(" ", "")
    app_tokens = set(app_label.lower().replace("-", " ").replace("_", " ").split()) if app_label else set()
    is_non_vpn = compact_label == "nonvpn" or "nonvpn" in label_tokens
    is_vpn = (
        not is_non_vpn
        and (
            "vpn" in label_tokens
            or "tor" in label_tokens
            or vpn_flag in {"1", "true", "yes", "vpn"}
            or "vpn" in app_tokens
        )
    )

    src_ip = str(_pick(idx, "src_ip", "source_ip", "ip") or "").strip() or None
    dst_ip = str(_pick(idx, "dst_ip", "destination_ip", "server_ip", "gateway_ip") or "").strip() or None
    if not src_ip and not dst_ip:
        return None
    payload: Dict[str, Any] = {
        "timestamp": _to_iso_utc(
            _pick(idx, "timestamp", "flow_start_time", "start_time", "stime"),
            fallback_now=True,
        ),
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "device_id": _pick(idx, "device_id", "session_id", "flow_id"),
        "gateway_id": dst_ip or _pick(idx, "gateway_id", "service_id"),
        "username": _pick(idx, "username", "user", "principal"),
        "result": "success",
        "protocol": _pick(idx, "protocol", "proto", "vpn_proto"),
        "provider": _pick(idx, "provider", "vpn_provider") or (app_label or label or dataset_name),
        "asn": _as_int(_pick(idx, "asn", "src_asn")),
        "request_fingerprint": _pick(idx, "flow_id", "session_id"),
        "dataset": dataset_name,
        "app_label": app_label or None,
        "benchmark_label": label or None,
        "vpn_detected": bool(is_vpn),
        "confirmed_benign": True if not is_vpn else None,
    }
    return NormalizedConnectorRecord(
        connector_key="vpn_gateway_session_v1",
        payload={k: v for k, v in payload.items() if v is not None},
        confidence=confidence,
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
    max_records: Optional[int] = None,
    sleep_every: Optional[int] = None,
    sleep_sec: float = 65.0,
    retry_on_rate_limit: bool = False,
) -> IngestionJobStats:
    svc = IngestionService(db, pseudonym_salt=settings.pseudonym_salt or None)
    total = accepted = duplicates = skipped = errors = 0
    processed_since_sleep = 0

    for record in records:
        if max_records is not None and total >= max(0, int(max_records)):
            break
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
            processed_since_sleep += 1
            if sleep_every and processed_since_sleep >= max(1, int(sleep_every)):
                log.info("real_data_ingest_pause sleep_sec=%s processed=%s", sleep_sec, processed_since_sleep)
                time.sleep(max(0.0, float(sleep_sec)))
                processed_since_sleep = 0
        except PermissionError as exc:
            if retry_on_rate_limit and "Rate limit exceeded" in str(exc):
                log.warning("real_data_rate_limit_pause connector=%s sleep_sec=%s", record.connector_key, sleep_sec)
                time.sleep(max(0.0, float(sleep_sec)))
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
                    processed_since_sleep = 0
                    continue
                except Exception as retry_exc:
                    errors += 1
                    log.exception(
                        "real_data_ingest_retry_failed connector=%s err=%s payload=%s",
                        record.connector_key,
                        retry_exc,
                        record.payload,
                    )
                    continue
            errors += 1
            log.exception(
                "real_data_ingest_failed connector=%s err=%s payload=%s",
                record.connector_key,
                exc,
                record.payload,
            )
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
            max_records=args.max_records if hasattr(args, "max_records") else None,
            sleep_every=args.sleep_every if hasattr(args, "sleep_every") else None,
            sleep_sec=args.sleep_sec if hasattr(args, "sleep_sec") else 65.0,
        )
    finally:
        db.close()


def normalize_paysim_row(
    row: Mapping[str, Any],
    *,
    dataset_name: str = "paysim_ke",
) -> Optional[NormalizedConnectorRecord]:
    """
    Map a PaySim-format mobile-money row to a TRANSACTION_EVENT via core_banking_tx_v1.

    Only fraud rows (isFraud=1) with transferable types are ingested — benign
    transactions are already represented in the graph through other event sources.
    This produces the mule-chain graph structure: TRANSFER → TRANSFER → CASH_OUT
    across a ring of accounts, which is the core M-Pesa fraud pattern.
    """
    is_fraud = str(row.get("isFraud", "0")).strip()
    if is_fraud not in ("1", "True", "true"):
        return None

    tx_type = str(row.get("type", "") or "").strip().upper()
    if tx_type not in ("CASH_OUT", "TRANSFER", "DEBIT"):
        return None

    # PaySim step = 1-based hour counter (744 steps = 31-day simulation).
    # Anchor to 2024-01-01 UTC so events land in a realistic window.
    step = max(1, int(float(row.get("step", 1) or 1)))
    ts_dt = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=(step - 1) % 744)

    amount = _as_float({"v": row.get("amount", 0)}, ("v",)) or 0.0
    name_orig = str(row.get("nameOrig", "") or "").strip() or None
    name_dest = str(row.get("nameDest", "") or "").strip() or None

    if not name_orig and not name_dest:
        return None

    payload: Dict[str, Any] = {
        "timestamp": ts_dt.isoformat(),
        "amount": amount,
        "currency": "KES",
        "channel": f"mpesa_{tx_type.lower()}",
        "dataset": dataset_name,
    }
    if name_orig:
        payload["account_from"] = name_orig
    if name_dest:
        payload["account_to"] = name_dest

    # Higher confidence when the transaction was also flagged by PaySim's rule engine.
    is_flagged = str(row.get("isFlaggedFraud", "0")).strip() in ("1", "True", "true")
    return NormalizedConnectorRecord(
        connector_key="core_banking_tx_v1",
        payload=payload,
        confidence=0.95 if is_flagged else 0.87,
    )


def _iter_paysim_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    dataset_name: str,
) -> Iterator[NormalizedConnectorRecord]:
    for row in rows:
        record = normalize_paysim_row(row, dataset_name=dataset_name)
        if record is not None:
            yield record


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


def _iter_vpn_benchmark_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    dataset_name: str,
) -> Iterator[NormalizedConnectorRecord]:
    for row in rows:
        record = normalize_vpn_benchmark_row(row, dataset_name=dataset_name)
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
            max_records=args.max_records if hasattr(args, "max_records") else None,
            sleep_every=args.sleep_every if hasattr(args, "sleep_every") else None,
            sleep_sec=args.sleep_sec if hasattr(args, "sleep_sec") else 65.0,
        )
    finally:
        db.close()


def _run_feodo_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = load_feodo_rows(
        feodo_file=args.feodo_file,
        feodo_url=args.feodo_url,
        timeout_sec=args.timeout_sec,
    )
    records = build_feodo_records(rows, confidence=args.confidence)
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            max_records=args.max_records if hasattr(args, "max_records") else None,
            sleep_every=args.sleep_every if hasattr(args, "sleep_every") else None,
            sleep_sec=args.sleep_sec if hasattr(args, "sleep_sec") else 65.0,
        )
    finally:
        db.close()


def _run_urlhaus_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = load_urlhaus_rows(
        urlhaus_file=args.urlhaus_file,
        urlhaus_url=args.urlhaus_url,
        auth_key=args.auth_key,
        timeout_sec=args.timeout_sec,
    )
    records = build_urlhaus_records(rows, confidence=args.confidence)
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            max_records=args.max_records,
            sleep_every=args.sleep_every,
            sleep_sec=args.sleep_sec,
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


def _run_threatfox_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = load_threatfox_rows(
        threatfox_file=args.threatfox_file,
        threatfox_url=args.threatfox_url,
        timeout_sec=args.timeout_sec,
    )
    records = build_threatfox_records(rows, confidence=args.confidence)
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            max_records=args.max_records,
            sleep_every=args.sleep_every,
            sleep_sec=args.sleep_sec,
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


def _run_malwarebazaar_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = load_malwarebazaar_rows(
        malwarebazaar_file=args.malwarebazaar_file,
        malwarebazaar_url=args.malwarebazaar_url,
        timeout_sec=args.timeout_sec,
    )
    records = build_malwarebazaar_records(rows, confidence=args.confidence)
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            max_records=args.max_records,
            sleep_every=args.sleep_every,
            sleep_sec=args.sleep_sec,
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


def _run_otx_job(args: argparse.Namespace) -> IngestionJobStats:
    pulses = load_otx_pulses(
        otx_file=args.otx_file,
        api_key=args.otx_api_key,
        otx_url=args.otx_url,
        timeout_sec=args.timeout_sec,
        limit=args.limit,
        modified_since=args.modified_since,
    )

    db = SessionLocal()
    try:
        if not args.skip_stix_import:
            bundle = build_otx_stix_bundle(pulses)
            imported = import_stix_bundle(db=db, bundle=bundle, source=args.threat_source)
            log.info("otx_stix_imported imported=%s source=%s", imported.get("imported"), args.threat_source)

        if args.stix_only:
            return IngestionJobStats(total_records=0, accepted=0, duplicates=0, skipped=0, errors=0)

        records = build_otx_indicator_records(pulses, confidence=args.confidence)
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            max_records=args.max_records,
            sleep_every=args.sleep_every,
            sleep_sec=args.sleep_sec,
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


def _run_vpn_benchmark_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = iter_rows_from_path(args.input_file)
    records = _iter_vpn_benchmark_records(rows, dataset_name=args.dataset_name or "iscx_vpn2016")
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            max_records=args.max_records,
            sleep_every=args.sleep_every,
            sleep_sec=args.sleep_sec,
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


def _run_ddos_benchmark_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = iter_rows_from_path(args.input_file)
    if args.dataset == "cic":
        records = _iter_cic_records(
            rows,
            service_id_prefix=args.service_id_prefix,
            dataset_name=args.dataset_name or "cic_ddos2019",
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
            max_records=args.max_records,
            sleep_every=args.sleep_every,
            sleep_sec=args.sleep_sec,
            retry_on_rate_limit=True,
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
    p_kev.add_argument("--sleep-every", type=int, default=450, dest="sleep_every", help="Sleep after every N records to avoid rate limits (default 450).")
    p_kev.add_argument("--sleep-sec", type=float, default=65.0, dest="sleep_sec", help="Seconds to sleep between batches (default 65).")

    p_traffic = sub.add_parser("traffic", help="Normalize CIC/CAIDA traffic rows into DDoS/Web events.")
    p_traffic.add_argument("--dataset", choices=("cic", "caida"), required=True, help="Traffic dataset family.")
    p_traffic.add_argument("--input-file", required=True, help="Input path (.csv/.json/.jsonl).")
    p_traffic.add_argument("--service-id-prefix", default="external", help="Service id prefix for mapped rows.")
    p_traffic.add_argument("--dataset-name", default=None, help="Optional dataset tag written into payload.")

    p_feodo = sub.add_parser("feodo", help="Import Feodo Tracker C2 indicators into DFIR events.")
    p_feodo.add_argument("--feodo-file", default=None, help="Local Feodo JSON/CSV file. If omitted, the live feed URL is used.")
    p_feodo.add_argument("--feodo-url", default=DEFAULT_FEODO_URL, help="Feodo feed URL.")
    p_feodo.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout for remote feed calls.")

    p_urlhaus = sub.add_parser("urlhaus", help="Import URLhaus malware URLs into DFIR events.")
    p_urlhaus.add_argument("--urlhaus-file", default=None, help="Local URLhaus CSV/JSON file. If omitted, the online CSV feed is used.")
    p_urlhaus.add_argument("--urlhaus-url", default=DEFAULT_URLHAUS_CSV_URL, help="URLhaus CSV feed URL.")
    p_urlhaus.add_argument("--auth-key", default=None, help="URLhaus auth-key. Falls back to URLHAUS_AUTH_KEY env var.")
    p_urlhaus.add_argument("--max-records", type=int, default=400, help="Maximum URLhaus DFIR events to emit per run.")
    p_urlhaus.add_argument("--sleep-every", type=int, default=400, help="Pause after this many URLhaus DFIR events.")
    p_urlhaus.add_argument("--sleep-sec", type=float, default=65.0, help="Pause duration used to avoid per-source ingest rate limits.")
    p_urlhaus.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout for remote feed calls.")

    p_threatfox = sub.add_parser("threatfox", help="Import ThreatFox malware IOCs into DFIR events.")
    p_threatfox.add_argument("--threatfox-file", default=None, help="Local ThreatFox JSON/CSV export.")
    p_threatfox.add_argument("--threatfox-url", default=DEFAULT_THREATFOX_URL, help="ThreatFox export URL.")
    p_threatfox.add_argument("--max-records", type=int, default=400, help="Maximum ThreatFox DFIR events to emit per run.")
    p_threatfox.add_argument("--sleep-every", type=int, default=400, help="Pause after this many ThreatFox DFIR events.")
    p_threatfox.add_argument("--sleep-sec", type=float, default=65.0, help="Pause duration used to avoid per-source ingest rate limits.")
    p_threatfox.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout for remote feed calls.")

    p_mbz = sub.add_parser("malwarebazaar", help="Import MalwareBazaar sample metadata into DFIR events.")
    p_mbz.add_argument("--malwarebazaar-file", default=None, help="Local MalwareBazaar JSON/CSV export.")
    p_mbz.add_argument("--malwarebazaar-url", default=DEFAULT_MALWAREBAZAAR_URL, help="MalwareBazaar API endpoint.")
    p_mbz.add_argument("--max-records", type=int, default=400, help="Maximum MalwareBazaar DFIR events to emit per run.")
    p_mbz.add_argument("--sleep-every", type=int, default=400, help="Pause after this many MalwareBazaar DFIR events.")
    p_mbz.add_argument("--sleep-sec", type=float, default=65.0, help="Pause duration used to avoid per-source ingest rate limits.")
    p_mbz.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout for remote feed calls.")

    p_otx = sub.add_parser("otx", help="Import AlienVault OTX indicators into STIX and DFIR events.")
    p_otx.add_argument("--otx-file", default=None, help="Local OTX pulse export JSON file.")
    p_otx.add_argument("--otx-api-key", default=None, help="OTX API key. Required when --otx-file is not used.")
    p_otx.add_argument("--otx-url", default=DEFAULT_OTX_SUBSCRIBED_URL, help="OTX subscribed pulses endpoint.")
    p_otx.add_argument("--threat-source", default="otx", help="Source label written to threat_intel_sync_log.")
    p_otx.add_argument("--modified-since", default=None, help="Optional OTX modified_since cursor.")
    p_otx.add_argument("--limit", type=int, default=100, help="Maximum subscribed pulses to fetch.")
    p_otx.add_argument("--max-records", type=int, default=400, help="Maximum mirrored DFIR events to emit per run.")
    p_otx.add_argument("--sleep-every", type=int, default=400, help="Pause after this many mirrored DFIR events.")
    p_otx.add_argument("--sleep-sec", type=float, default=65.0, help="Pause duration used to avoid per-source ingest rate limits.")
    p_otx.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout for remote feed calls.")
    p_otx.add_argument("--skip-stix-import", action="store_true", help="Skip STIX import and only emit DFIR events.")
    p_otx.add_argument("--stix-only", action="store_true", help="Import STIX indicators only and skip DFIR event creation.")

    # ---- PaySim ----
    p_paysim = sub.add_parser("paysim", help="Ingest PaySim Africa mobile-money fraud CSV.")
    p_paysim.add_argument("--input-file", required=True, help="Path to paysim CSV (e.g. PS_20174392719_1491204439457_log.csv).")
    p_paysim.add_argument("--include-benign", action="store_true", help="Also include non-fraud transactions (sampled).")
    p_paysim.add_argument("--max-benign", type=int, default=5000, help="Max benign rows to include when --include-benign is set.")
    p_paysim.add_argument("--sleep-every", type=int, default=450, dest="sleep_every", help="Sleep after every N records to avoid rate limits.")
    p_paysim.add_argument("--sleep-sec", type=float, default=65.0, dest="sleep_sec", help="Seconds to sleep between batches.")

    p_vpn = sub.add_parser("vpn-benchmark", help="Ingest VPN benchmark rows into LOGIN_EVENT via vpn_gateway_session_v1.")
    p_vpn.add_argument("--input-file", required=True, help="Path to VPN benchmark CSV/JSON/JSONL.")
    p_vpn.add_argument("--dataset-name", default="iscx_vpn2016", help="Dataset tag written into payload.")
    p_vpn.add_argument("--max-records", type=int, default=5000, help="Maximum VPN benchmark rows to emit per run.")
    p_vpn.add_argument("--sleep-every", type=int, default=450, dest="sleep_every", help="Sleep after every N records to avoid rate limits.")
    p_vpn.add_argument("--sleep-sec", type=float, default=65.0, dest="sleep_sec", help="Seconds to sleep between batches.")

    p_ddos = sub.add_parser("ddos-benchmark", help="Ingest DDoS benchmark rows into DDOS_SIGNAL_EVENT.")
    p_ddos.add_argument("--dataset", choices=("cic", "caida"), required=True, help="DDoS benchmark family.")
    p_ddos.add_argument("--input-file", required=True, help="Input path (.csv/.json/.jsonl).")
    p_ddos.add_argument("--service-id-prefix", default="external", help="Service id prefix for mapped rows.")
    p_ddos.add_argument("--dataset-name", default=None, help="Optional dataset tag written into payload.")
    p_ddos.add_argument("--max-records", type=int, default=5000, help="Maximum benchmark rows to emit per run.")
    p_ddos.add_argument("--sleep-every", type=int, default=450, dest="sleep_every", help="Sleep after every N records to avoid rate limits.")
    p_ddos.add_argument("--sleep-sec", type=float, default=65.0, dest="sleep_sec", help="Seconds to sleep between batches.")

    # ---- PPRA Kenya OCDS ----
    p_ppra = sub.add_parser("ppra", help="Deprecated: use the corruption-domain PPRA ingesters instead.")
    p_ppra.add_argument("--input-file", required=True, help="Path to PPRA OCDS flattened CSV.")
    p_ppra.add_argument("--anomalies-only", action="store_true", help="Only ingest rows that have at least one anomaly flag.")
    p_ppra.add_argument("--sleep-every", type=int, default=450, dest="sleep_every", help="Sleep after every N records to avoid rate limits.")
    p_ppra.add_argument("--sleep-sec", type=float, default=65.0, dest="sleep_sec", help="Seconds to sleep between batches.")

    # ---- UNSW-NB15 ----
    p_unsw = sub.add_parser("unsw", help="Ingest UNSW-NB15 network intrusion CSV.")
    p_unsw.add_argument("--input-file", required=True, help="Path to UNSW-NB15 CSV file.")
    p_unsw.add_argument("--service-id-prefix", default="unsw", help="Prefix for derived service_id (e.g. 'ke-noc').")
    p_unsw.add_argument("--dataset-name", default="unsw_nb15", help="Dataset tag written into payload.")
    p_unsw.add_argument("--sleep-every", type=int, default=450, dest="sleep_every", help="Sleep after every N records to avoid rate limits.")
    p_unsw.add_argument("--sleep-sec", type=float, default=65.0, dest="sleep_sec", help="Seconds to sleep between batches.")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_cli()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.job == "kev-epss":
        stats = _run_kev_epss_job(args)
    elif args.job == "traffic":
        stats = _run_traffic_job(args)
    elif args.job == "feodo":
        stats = _run_feodo_job(args)
    elif args.job == "urlhaus":
        stats = _run_urlhaus_job(args)
    elif args.job == "threatfox":
        stats = _run_threatfox_job(args)
    elif args.job == "malwarebazaar":
        stats = _run_malwarebazaar_job(args)
    elif args.job == "paysim":
        stats = _run_paysim_job(args)
    elif args.job == "vpn-benchmark":
        stats = _run_vpn_benchmark_job(args)
    elif args.job == "ddos-benchmark":
        stats = _run_ddos_benchmark_job(args)
    elif args.job == "ppra":
        stats = _run_ppra_job(args)
    elif args.job == "unsw":
        stats = _run_unsw_job(args)
    else:
        stats = _run_otx_job(args)

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


# =============================================================================
# PaySim — Africa synthetic mobile-money fraud (Kaggle ealaxi/paysim1)
# CSV columns: step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,
#              nameDest,oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud
# =============================================================================

_PAYSIM_BASE_TS = 1_700_000_000.0  # 2023-11-14 as sim epoch (arbitrary but realistic)
_PAYSIM_STEP_SECS = 3600.0  # each step == 1 hour

_PAYSIM_FRAUD_CHANNELS = {
    "CASH_OUT": "mobile_cash_out",
    "TRANSFER": "mobile_transfer",
    "CASH_IN": "mobile_cash_in",
    "PAYMENT": "mobile_payment",
    "DEBIT": "mobile_debit",
}


def normalize_paysim_row(
    row: Mapping[str, Any],
    *,
    confidence: float = 0.91,
    fraud_only: bool = True,
) -> Optional[NormalizedConnectorRecord]:
    idx = _row_index(row)

    is_fraud = _as_int(_pick(idx, "isfraud", "fraud", "label")) or 0
    is_flagged = _as_int(_pick(idx, "isflaggedfraud", "flaggedfraud")) or 0
    if fraud_only and not is_fraud and not is_flagged:
        return None

    step = _as_float(_pick(idx, "step")) or 0.0
    ts = _to_iso_utc(_PAYSIM_BASE_TS + step * _PAYSIM_STEP_SECS)

    txn_type = str(_pick(idx, "type", "transactiontype") or "TRANSFER").strip().upper()
    amount = _as_float(_pick(idx, "amount", "amt")) or 0.0

    name_orig = str(_pick(idx, "nameorig", "orig", "sender") or "").strip()
    name_dest = str(_pick(idx, "namedest", "dest", "receiver") or "").strip()

    payload: Dict[str, Any] = {
        "timestamp": ts,
        "account_from": name_orig or None,
        "account_to": name_dest or None,
        "amount": amount,
        "currency": "KES",
        "channel": _PAYSIM_FRAUD_CHANNELS.get(txn_type, "mobile_money"),
        "transaction_type": txn_type,
        "is_fraud": bool(is_fraud),
        "is_flagged": bool(is_flagged),
        "old_balance_orig": _as_float(_pick(idx, "oldbalanceorg", "oldbalanceorig")),
        "new_balance_orig": _as_float(_pick(idx, "newbalanceorig", "newbalanceoriginal")),
        "old_balance_dest": _as_float(_pick(idx, "oldbalancedest")),
        "new_balance_dest": _as_float(_pick(idx, "newbalancedest")),
        "dataset": "paysim",
    }

    return NormalizedConnectorRecord(
        connector_key="core_banking_tx_v1",
        payload={k: v for k, v in payload.items() if v is not None},
        confidence=confidence if is_fraud else max(0.3, confidence - 0.4),
    )


def build_paysim_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    confidence: float = 0.91,
    fraud_only: bool = True,
    max_benign: int = 5000,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    benign_count = 0
    for row in rows:
        idx = _row_index(row)
        is_fraud = _as_int(_pick(idx, "isfraud", "fraud", "label")) or 0
        is_flagged = _as_int(_pick(idx, "isflaggedfraud", "flaggedfraud")) or 0
        if not is_fraud and not is_flagged:
            if fraud_only:
                continue
            if benign_count >= max_benign:
                continue
            benign_count += 1
        rec = normalize_paysim_row(row, confidence=confidence, fraud_only=False)
        if rec is not None:
            out.append(rec)
    return out


# =============================================================================
# PPRA Kenya — Open Contracting Data Standard (OCDS) procurement releases
# Source: https://data.open-contracting.org/en/publication/147/download
# Supports flattened CSV export from the OCDS portal.
# Maps procurement contracts → TRANSACTION_EVENT for anomaly detection.
# =============================================================================

_PPRA_DIRECT_METHODS = {"direct", "directcontract", "singlesource", "restricted", "emergency"}


def _ppra_anomaly_flags(idx: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    method = str(_pick(idx, "tenderprocurementmethod", "procurementmethod", "method") or "").strip().lower()
    method_norm = re.sub(r"[^a-z]", "", method)
    if method_norm in _PPRA_DIRECT_METHODS:
        flags.append("sole_source_procurement")

    n_tenderers = _as_int(_pick(idx, "tendernumberoftenderers", "numberoftenderers", "bidders"))
    if n_tenderers is not None and n_tenderers <= 1:
        flags.append("single_bidder")

    tender_val = _as_float(_pick(idx, "tendervalueamount", "tenderamount", "estimatedvalue"))
    contract_val = _as_float(_pick(idx, "contractvalueamount", "contractamount", "awardedvalue"))
    if tender_val and contract_val and tender_val > 0:
        variance = (contract_val - tender_val) / tender_val
        if variance > 0.15:
            flags.append("contract_overrun_15pct")
        elif variance < -0.15:
            flags.append("contract_underrun_15pct")

    return flags


def normalize_ppra_row(
    row: Mapping[str, Any],
    *,
    confidence: float = 0.82,
) -> Optional[NormalizedConnectorRecord]:
    idx = _row_index(row)

    ocid = str(_pick(idx, "ocid", "id", "releaseid") or "").strip()
    if not ocid:
        return None

    date_str = _pick(idx, "date", "releasedate", "contractdatesigned", "tenderdatesubmissionuntil")
    ts = _to_iso_utc(date_str, fallback_now=True)

    buyer_id = str(_pick(idx, "buyeridentifierid", "buyerid", "procuringentityid", "buyername") or "").strip()
    supplier_id = str(
        _pick(idx, "suppliersidentifierid", "supplierid", "awardedcompanyid", "contractorsid") or ""
    ).strip()

    amount = _as_float(
        _pick(idx, "contractvalueamount", "contractamount", "awardedvalue", "tendervalueamount")
    )
    currency = str(_pick(idx, "contractvaluecurrency", "currency", "tendervaluecurrency") or "KES").strip()

    title = str(_pick(idx, "tendertitle", "title", "procurementtitle", "description") or "").strip()
    method = str(_pick(idx, "tenderprocurementmethod", "procurementmethod") or "").strip()
    n_tenderers = _as_int(_pick(idx, "tendernumberoftenderers", "numberoftenderers"))

    flags = _ppra_anomaly_flags(idx)
    anomaly_score = min(1.0, 0.4 + len(flags) * 0.2)

    payload: Dict[str, Any] = {
        "timestamp": ts,
        "account_from": buyer_id or None,
        "account_to": supplier_id or None,
        "amount": amount,
        "currency": currency,
        "channel": "procurement",
        "transaction_ref": ocid,
        "procurement_method": method or None,
        "n_tenderers": n_tenderers,
        "title": title[:200] if title else None,
        "anomaly_flags": flags if flags else None,
        "dataset": "ppra_ke",
    }

    effective_confidence = confidence if not flags else min(0.97, confidence + anomaly_score * 0.15)

    return NormalizedConnectorRecord(
        connector_key="core_banking_tx_v1",
        payload={k: v for k, v in payload.items() if v is not None},
        confidence=effective_confidence,
    )


def build_ppra_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    confidence: float = 0.82,
    anomalies_only: bool = False,
) -> List[NormalizedConnectorRecord]:
    out: List[NormalizedConnectorRecord] = []
    for row in rows:
        rec = normalize_ppra_row(row, confidence=confidence)
        if rec is None:
            continue
        if anomalies_only:
            idx = _row_index(row)
            if not _ppra_anomaly_flags(idx):
                continue
        out.append(rec)
    return out


# =============================================================================
# UNSW-NB15 — Network intrusion dataset (UNSW Canberra)
# Source: kaggle.com/datasets/dhoogla/unswnb15 or research.unsw.edu.au
# CSV columns include: srcip, sport, dstip, dsport, proto, state, dur, sbytes,
#   dbytes, Stime, Ltime, attack_cat, Label
# Maps: DoS → DDOS_SIGNAL_EVENT; Backdoor/Exploit/Worm/Shellcode → DFIR_FINDING_EVENT;
#       Fuzzer/Generic/Recon/Analysis → WEB_ATTACK_EVENT
# =============================================================================

_UNSW_DFIR_CATS = {"backdoor", "backdoors", "exploit", "exploits", "shellcode", "worms", "worm"}
_UNSW_WEB_CATS = {"fuzzers", "fuzzer", "generic", "reconnaissance", "analysis"}
_UNSW_DOS_CATS = {"dos"}


def _unsw_attack_type(cat: str) -> str:
    c = cat.strip().lower()
    if "sql" in c:
        return "sql_injection"
    if "xss" in c:
        return "xss"
    if "fuzz" in c:
        return "fuzzing"
    if "recon" in c:
        return "reconnaissance"
    if "analysis" in c:
        return "traffic_analysis"
    return "generic_attack"


def normalize_unsw_row(
    row: Mapping[str, Any],
    *,
    service_id_prefix: str = "unsw",
    dataset_name: str = "unsw_nb15",
    confidence: float = 0.89,
) -> Optional[NormalizedConnectorRecord]:
    idx = _row_index(row)

    label = _as_int(_pick(idx, "label")) or 0
    attack_cat = str(_pick(idx, "attackcat", "attack_cat", "category") or "").strip().lower()

    if not label and not attack_cat:
        return None

    ts_raw = _pick(idx, "stime", "starttime", "timestamp", "time")
    ts = _to_iso_utc(ts_raw, fallback_now=True)

    src_ip = str(_pick(idx, "srcip", "src_ip", "source") or "").strip() or None
    dst_ip = str(_pick(idx, "dstip", "dst_ip", "destination") or "").strip() or None
    dst_port = _as_int(_pick(idx, "dsport", "dport", "dst_port", "destination_port"))
    proto = str(_pick(idx, "proto", "protocol") or "").strip() or None

    service_id = f"{service_id_prefix}:{dst_ip}" if dst_ip else f"{service_id_prefix}:unknown"
    endpoint = f"port:{dst_port}" if dst_port is not None else None

    sbytes = _as_int(_pick(idx, "sbytes", "source_bytes"))
    dbytes = _as_int(_pick(idx, "dbytes", "destination_bytes"))
    dur = _as_float(_pick(idx, "dur", "duration"))

    # DoS
    if attack_cat in _UNSW_DOS_CATS or (label and not attack_cat):
        payload: Dict[str, Any] = {
            "timestamp": ts,
            "service_id": service_id,
            "endpoint": endpoint,
            "method": proto,
            "request_rate": (sbytes / max(0.001, dur)) if sbytes and dur else None,
            "unique_ips_count": 1 if src_ip else None,
            "dataset": dataset_name,
            "attack_label": attack_cat or "dos",
        }
        return NormalizedConnectorRecord(
            connector_key="cloudflare_ddos_v1",
            payload={k: v for k, v in payload.items() if v is not None},
            confidence=confidence,
        )

    # DFIR (Backdoor, Exploit, Shellcode, Worm)
    if attack_cat in _UNSW_DFIR_CATS:
        payload = {
            "timestamp": ts,
            "source": "unsw_nb15",
            "host": dst_ip or "unknown",
            "artifact_name": f"UNSW-NB15:{attack_cat}",
            "finding_type": attack_cat,
            "severity": "high" if attack_cat in {"exploit", "exploits", "shellcode"} else "medium",
            "client_ip": src_ip,
            "dataset": dataset_name,
            "attack_label": attack_cat,
            "src_bytes": sbytes,
            "dst_bytes": dbytes,
        }
        return NormalizedConnectorRecord(
            connector_key="velociraptor_artifact_v1",
            payload={k: v for k, v in payload.items() if v is not None},
            confidence=confidence,
        )

    # Web / Fuzzer / Recon / Generic
    if attack_cat in _UNSW_WEB_CATS or attack_cat:
        payload = {
            "timestamp": ts,
            "service_id": service_id,
            "endpoint": endpoint,
            "attack_type": _unsw_attack_type(attack_cat),
            "status": "detected",
            "src_ip": src_ip,
            "method": proto,
            "dataset": dataset_name,
            "attack_label": attack_cat,
        }
        return NormalizedConnectorRecord(
            connector_key="waf_api_attack_v1",
            payload={k: v for k, v in payload.items() if v is not None},
            confidence=confidence,
        )

    return None


def build_unsw_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    service_id_prefix: str = "unsw",
    dataset_name: str = "unsw_nb15",
    confidence: float = 0.89,
) -> Iterator[NormalizedConnectorRecord]:
    for row in rows:
        rec = normalize_unsw_row(
            row,
            service_id_prefix=service_id_prefix,
            dataset_name=dataset_name,
            confidence=confidence,
        )
        if rec is not None:
            yield rec


# =============================================================================
# Job runners for new datasets
# =============================================================================

def _run_paysim_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = iter_rows_from_path(args.input_file)
    records = build_paysim_records(
        rows,
        confidence=args.confidence,
        fraud_only=not args.include_benign,
        max_benign=args.max_benign,
    )
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=records,
            source_api_key=args.source_api_key,
            classification=args.classification,
            sleep_every=getattr(args, "sleep_every", 450),
            sleep_sec=getattr(args, "sleep_sec", 65.0),
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


def _run_ppra_job(args: argparse.Namespace) -> IngestionJobStats:
    raise ValueError(
        "The generic 'ppra' real-data job is deprecated because PPRA procurement data now belongs "
        "to the corruption-domain pipeline. Use 'python -m app.analytics.corruption.ppra_awards_ingest "
        "--input-file ...' for award data or 'python -m app.analytics.corruption.ppra_arb_ingest "
        "--input-file ...' for review-board decisions."
    )


def _run_unsw_job(args: argparse.Namespace) -> IngestionJobStats:
    rows = iter_rows_from_path(args.input_file)
    records = build_unsw_records(
        rows,
        service_id_prefix=args.service_id_prefix,
        dataset_name=args.dataset_name or "unsw_nb15",
        confidence=args.confidence,
    )
    db = SessionLocal()
    try:
        return ingest_records_via_connectors(
            db=db,
            records=iter(list(records)),
            source_api_key=args.source_api_key,
            classification=args.classification,
            sleep_every=getattr(args, "sleep_every", 450),
            sleep_sec=getattr(args, "sleep_sec", 65.0),
            retry_on_rate_limit=True,
        )
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
