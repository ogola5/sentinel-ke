#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Iterable
from urllib import error, request


def _load_cursor(path: Path | None) -> int:
    if not path or not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return max(0, int(payload.get("processed", 0) or 0))


def _save_cursor(path: Path | None, processed: int) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"processed": processed}, indent=2), encoding="utf-8")


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("jsonl rows must decode to objects")
        items.append(payload)
    return items


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("json-array input must be a JSON list")
    items: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("json-array rows must decode to objects")
        items.append(row)
    return items


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{str(k): v for k, v in row.items()} for row in reader]


def _read_items(path: Path, input_format: str) -> list[dict[str, Any]]:
    normalized = input_format.strip().lower()
    if normalized == "auto":
        suffix = path.suffix.lower()
        if suffix in {".jsonl", ".ndjson"}:
            normalized = "jsonl"
        elif suffix == ".csv":
            normalized = "csv"
        elif suffix == ".json":
            normalized = "json-array"
        else:
            raise ValueError(f"unsupported input extension for auto mode: {suffix}")
    if normalized == "jsonl":
        return _read_json_lines(path)
    if normalized == "json-array":
        return _read_json_array(path)
    if normalized == "csv":
        return _read_csv_rows(path)
    raise ValueError(f"unsupported input format: {input_format}")


def _chunk(items: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def _post_batch(
    *,
    base_url: str,
    connector_key: str,
    api_key: str,
    source_api_key: str,
    confidence: float,
    classification: str,
    items: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "source_api_key": source_api_key,
            "confidence": confidence,
            "classification": classification,
            "items": items,
        }
    ).encode("utf-8")
    req = request.Request(
        url=f"{base_url.rstrip('/')}/v1/integrations/{connector_key}/batch",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bridge legacy CSV/JSON exports into Sentinel-KE connector ingestion.",
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--connector-key", required=True)
    parser.add_argument("--api-key", required=True, help="Sentinel API key for /v1/integrations/*")
    parser.add_argument("--source-api-key", required=True, help="Registered source_registry API key")
    parser.add_argument("--input", required=True, help="Path to CSV, JSONL, NDJSON, or JSON array")
    parser.add_argument("--input-format", default="auto", choices=["auto", "csv", "jsonl", "json-array"])
    parser.add_argument("--classification", default="RESTRICTED")
    parser.add_argument("--confidence", type=float, default=0.9)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--mode", choices=["once", "watch"], default="once")
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--cursor-file", default="", help="Persist processed row count for watch mode")
    parser.add_argument("--dry-run", action="store_true", help="Print batches instead of sending them")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"input file not found: {input_path}")
    cursor_path = Path(args.cursor_file).expanduser().resolve() if args.cursor_file else None
    processed = _load_cursor(cursor_path)

    while True:
        items = _read_items(input_path, args.input_format)
        pending = items[processed:]
        sent = 0
        accepted = 0

        for batch in _chunk(pending, max(1, args.batch_size)):
            if args.dry_run:
                _print_json(
                    {
                        "status": "dry_run",
                        "connector_key": args.connector_key,
                        "items": len(batch),
                        "sample": batch[:2],
                    }
                )
                sent += len(batch)
                accepted += len(batch)
                continue
            try:
                result = _post_batch(
                    base_url=args.base_url,
                    connector_key=args.connector_key,
                    api_key=args.api_key,
                    source_api_key=args.source_api_key,
                    confidence=args.confidence,
                    classification=args.classification,
                    items=batch,
                    timeout_seconds=args.timeout_seconds,
                )
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                _print_json(
                    {
                        "status": "http_error",
                        "connector_key": args.connector_key,
                        "code": exc.code,
                        "detail": detail[:500],
                        "failed_batch_items": len(batch),
                    }
                )
                raise SystemExit(1)
            except Exception as exc:  # pragma: no cover - operational path
                _print_json(
                    {
                        "status": "error",
                        "connector_key": args.connector_key,
                        "detail": str(exc),
                        "failed_batch_items": len(batch),
                    }
                )
                raise SystemExit(1)

            batch_results = result.get("results") or []
            batch_accepted = sum(1 for row in batch_results if row.get("status") == "accepted")
            sent += len(batch)
            accepted += batch_accepted
            _print_json(
                {
                    "status": "posted",
                    "connector_key": args.connector_key,
                    "sent": len(batch),
                    "accepted": batch_accepted,
                }
            )

        processed = len(items)
        _save_cursor(cursor_path, processed)
        _print_json(
            {
                "status": "idle" if args.mode == "watch" else "done",
                "connector_key": args.connector_key,
                "processed_rows": processed,
                "sent_rows": sent,
                "accepted_rows": accepted,
                "input": str(input_path),
            }
        )

        if args.mode != "watch":
            break
        time.sleep(max(1.0, args.poll_seconds))


if __name__ == "__main__":
    main()
