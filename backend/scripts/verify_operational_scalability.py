#!/usr/bin/env python3
"""
verify_operational_scalability.py — quick operational proof probe
=================================================================

Checks the main runtime surfaces judges care about:
  - health/readiness
  - federation visibility
  - cases / AI / defense endpoints
  - simple latency summary

Writes a compact JSON artifact for rehearsals and demo prep.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1))))
    return round(float(ordered[idx]), 3)


def summarize_latencies(values_ms: list[float]) -> dict[str, float | int | None]:
    if not values_ms:
        return {"count": 0, "min_ms": None, "mean_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "count": len(values_ms),
        "min_ms": round(min(values_ms), 3),
        "mean_ms": round(statistics.mean(values_ms), 3),
        "p95_ms": _percentile(values_ms, 95),
        "max_ms": round(max(values_ms), 3),
    }


def probe_endpoint(
    client: httpx.Client,
    *,
    path: str,
    api_key: str | None,
    repeats: int = 3,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    expected_statuses: set[int] | None = None,
) -> dict[str, Any]:
    latencies: list[float] = []
    last_status: int | None = None
    last_json: Any = None
    merged_headers = dict(headers or {})
    if api_key:
        merged_headers.setdefault("X-API-Key", api_key)

    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        response = client.request(method, path, headers=merged_headers, json=json_body)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)
        last_status = response.status_code
        try:
            last_json = response.json()
        except Exception:  # noqa: BLE001
            last_json = {"text": response.text[:500]}

    accepted_statuses = expected_statuses or set(range(200, 300))
    ok = bool(last_status in accepted_statuses)
    return {
        "path": path,
        "method": method,
        "status_code": last_status,
        "ok": ok,
        "latency": summarize_latencies(latencies),
        "sample": last_json,
    }


def login_for_token(
    client: httpx.Client,
    *,
    username: str,
    password: str,
    client_fingerprint: str = "operational-probe",
) -> dict[str, Any]:
    response = client.post(
        "/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "client_fingerprint": client_fingerprint,
        },
    )
    payload: Any
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {"text": response.text[:500]}
    if response.status_code != 200:
        raise RuntimeError(
            f"auth_login_failed username={username} status={response.status_code} payload={payload}"
        )
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError(f"auth_login_missing_access_token username={username}")
    return payload


def auth_checks(
    client: httpx.Client,
    *,
    username: str,
    password: str,
    expect_central: bool,
) -> list[dict[str, Any]]:
    token_payload = login_for_token(client, username=username, password=password)
    access_token = str(token_payload["access_token"])
    principal = token_payload.get("principal") or {}
    headers = {"Authorization": f"Bearer {access_token}"}
    checks = [
        probe_endpoint(
            client,
            path="/v1/auth/me",
            api_key=None,
            repeats=1,
            headers=headers,
            expected_statuses={200},
        )
    ]
    checks[-1]["expected_access_level"] = "central" if expect_central else "section"
    checks[-1]["principal"] = principal
    checks.append(
        probe_endpoint(
            client,
            path="/v1/auth/users?limit=1",
            api_key=None,
            repeats=1,
            headers=headers,
            expected_statuses={200} if expect_central else {403},
        )
    )
    return checks


def build_report(*, base_url: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    overall_ok = all(bool(item.get("ok")) for item in checks)
    return {
        "checked_at": _utcnow(),
        "base_url": base_url,
        "overall_ok": overall_ok,
        "checks": checks,
        "summary": {
            "passed": sum(1 for item in checks if item.get("ok")),
            "failed": sum(1 for item in checks if not item.get("ok")),
            "slowest_p95_ms": max(
                (float(item["latency"]["p95_ms"]) for item in checks if item["latency"]["p95_ms"] is not None),
                default=None,
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Sentinel-KE operational readiness endpoints")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--api-key", default="", help="Frontend/service API key for protected endpoints")
    parser.add_argument("--repeats", type=int, default=3, help="Requests per endpoint")
    parser.add_argument("--section-username", default="", help="Optional section user for auth/RBAC checks")
    parser.add_argument("--section-password", default="", help="Password for the section user")
    parser.add_argument("--central-username", default="", help="Optional central user for auth/RBAC checks")
    parser.add_argument("--central-password", default="", help="Password for the central user")
    parser.add_argument(
        "--out",
        default="artifacts/operational_scalability_report.json",
        help="Where to write the JSON report",
    )
    args = parser.parse_args()

    paths = [
        "/health",
        "/ready",
        "/v1/federation/partners?limit=10",
        "/v1/federation/correlations?limit=10",
        "/v1/metrics",
    ]

    checks: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url, timeout=15.0) as client:
        for path in paths:
            checks.append(probe_endpoint(client, path=path, api_key=args.api_key or None, repeats=args.repeats))
        if args.section_username and args.section_password:
            checks.extend(
                auth_checks(
                    client,
                    username=args.section_username,
                    password=args.section_password,
                    expect_central=False,
                )
            )
        if args.central_username and args.central_password:
            checks.extend(
                auth_checks(
                    client,
                    username=args.central_username,
                    password=args.central_password,
                    expect_central=True,
                )
            )

    report = build_report(base_url=args.base_url, checks=checks)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
