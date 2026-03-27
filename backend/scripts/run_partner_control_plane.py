#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class PartnerControlPlaneHandler(BaseHTTPRequestHandler):
    server_version = "SentinelPartnerControlPlane/1.0"

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _record_receipt(self, receipt: dict[str, Any]) -> None:
        self.server.receipts.append(receipt)  # type: ignore[attr-defined]
        receipts_path: Path | None = self.server.receipts_path  # type: ignore[attr-defined]
        if receipts_path:
            receipts_path.parent.mkdir(parents=True, exist_ok=True)
            receipts_path.write_text(
                json.dumps(self.server.receipts, indent=2),  # type: ignore[attr-defined]
                encoding="utf-8",
            )

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(
                {
                    "status": "ok",
                    "service": "partner-control-plane",
                    "receipts": len(self.server.receipts),  # type: ignore[attr-defined]
                    "updated_at": utcnow_iso(),
                }
            )
            return
        if self.path == "/receipts":
            self._write_json({"items": self.server.receipts})  # type: ignore[attr-defined]
            return
        self._write_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/apply", "/containment"}:
            self._write_json({"error": "not_found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length)
        signature = self.headers.get("X-Sentinel-Signature", "")
        expected = _sign(self.server.shared_secret, body)  # type: ignore[attr-defined]
        verified = bool(signature) and hmac.compare_digest(signature, expected)

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"raw": body.decode("utf-8", errors="replace")}

        action_type = str(payload.get("action_type") or "").strip().lower()
        target = str(payload.get("target") or "").strip()

        if not verified:
            receipt = {
                "received_at": utcnow_iso(),
                "status": "rejected",
                "reason": "invalid_signature",
                "action_type": action_type,
                "target": target,
            }
            self._record_receipt(receipt)
            self._write_json(receipt, status=HTTPStatus.FORBIDDEN)
            return

        accepted_actions = set(self.server.accepted_actions)  # type: ignore[attr-defined]
        if accepted_actions and action_type not in accepted_actions:
            receipt = {
                "received_at": utcnow_iso(),
                "status": "rejected",
                "reason": "unsupported_action",
                "action_type": action_type,
                "target": target,
            }
            self._record_receipt(receipt)
            self._write_json(receipt, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            return

        receipt = {
            "received_at": utcnow_iso(),
            "status": "accepted",
            "action_type": action_type,
            "target": target,
            "section_code": payload.get("section_code"),
            "action_id": payload.get("action_id"),
            "signature_verified": True,
            "note": "Partner control plane accepted the containment request.",
        }
        self._record_receipt(receipt)
        self._write_json(receipt, status=HTTPStatus.OK)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an external partner containment control-plane simulator.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18100)
    parser.add_argument(
        "--shared-secret",
        default="sentinel-partner-demo-secret",
        help="Shared HMAC secret used to verify X-Sentinel-Signature.",
    )
    parser.add_argument(
        "--accept-action",
        action="append",
        default=[],
        help="Limit accepted actions. Repeat for multiple action types. Default: accept all.",
    )
    parser.add_argument(
        "--receipts-file",
        default="/tmp/sentinel_partner_receipts.json",
        help="Where to persist accepted/rejected receipts.",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), PartnerControlPlaneHandler)
    server.shared_secret = args.shared_secret  # type: ignore[attr-defined]
    server.accepted_actions = [str(item).strip().lower() for item in args.accept_action if str(item).strip()]  # type: ignore[attr-defined]
    server.receipts = []  # type: ignore[attr-defined]
    server.receipts_path = Path(args.receipts_file) if args.receipts_file else None  # type: ignore[attr-defined]

    print(
        json.dumps(
            {
                "status": "listening",
                "host": args.host,
                "port": args.port,
                "endpoint": f"http://{args.host}:{args.port}/apply",
                "receipts_path": args.receipts_file,
                "accepted_actions": server.accepted_actions or "all",
            }
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
