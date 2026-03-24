from __future__ import annotations

import json

import httpx

from scripts import verify_operational_scalability as probe


def test_summarize_latencies_returns_expected_stats():
    out = probe.summarize_latencies([10.0, 20.0, 30.0, 40.0])
    assert out["count"] == 4
    assert out["min_ms"] == 10.0
    assert out["mean_ms"] == 25.0
    assert out["p95_ms"] == 40.0
    assert out["max_ms"] == 40.0


def test_probe_endpoint_collects_status_and_sample():
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "frontend-secret"
        return httpx.Response(200, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(_handler), base_url="http://testserver") as client:
        out = probe.probe_endpoint(client, path="/health", api_key="frontend-secret", repeats=2)

    assert out["ok"] is True
    assert out["status_code"] == 200
    assert out["sample"]["status"] == "ok"
    assert out["latency"]["count"] == 2


def test_probe_endpoint_can_expect_non_2xx_status():
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    with httpx.Client(transport=httpx.MockTransport(_handler), base_url="http://testserver") as client:
        out = probe.probe_endpoint(
            client,
            path="/v1/auth/users",
            api_key=None,
            repeats=1,
            expected_statuses={403},
        )

    assert out["ok"] is True
    assert out["status_code"] == 403


def test_auth_checks_cover_section_and_central_paths():
    def _handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization")
        if request.url.path == "/v1/auth/login":
            payload = json.loads(request.content.decode("utf-8"))
            if payload["username"] == "central_user":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "central-token",
                        "principal": {"access_level": "central"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "access_token": "section-token",
                    "principal": {"access_level": "section"},
                },
            )
        if request.url.path == "/v1/auth/me":
            return httpx.Response(200, json={"access_level": "central" if auth == "Bearer central-token" else "section"})
        if request.url.path == "/v1/auth/users":
            status = 200 if auth == "Bearer central-token" else 403
            return httpx.Response(status, json={"status": status})
        raise AssertionError(f"unexpected path {request.url.path}")

    with httpx.Client(transport=httpx.MockTransport(_handler), base_url="http://testserver") as client:
        section_checks = probe.auth_checks(client, username="section_user", password="pw", expect_central=False)
        central_checks = probe.auth_checks(client, username="central_user", password="pw", expect_central=True)

    assert section_checks[0]["status_code"] == 200
    assert section_checks[1]["status_code"] == 403
    assert central_checks[0]["status_code"] == 200
    assert central_checks[1]["status_code"] == 200


def test_bearer_headers_from_login_returns_authorization_header():
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/auth/login"
        return httpx.Response(200, json={"access_token": "central-token", "principal": {"access_level": "central"}})

    with httpx.Client(transport=httpx.MockTransport(_handler), base_url="http://testserver") as client:
        headers = probe.bearer_headers_from_login(client, username="central_user", password="pw")

    assert headers == {"Authorization": "Bearer central-token"}


def test_build_report_counts_passed_and_failed_checks():
    report = probe.build_report(
        base_url="http://localhost:8000",
        checks=[
            {"ok": True, "latency": {"p95_ms": 40.0}},
            {"ok": False, "latency": {"p95_ms": 25.0}},
        ],
    )
    assert report["overall_ok"] is False
    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["slowest_p95_ms"] == 40.0
