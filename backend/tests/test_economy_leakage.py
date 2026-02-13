from datetime import datetime, timedelta, timezone

from app.economy.leakage import (
    detect_bid_rotation_ring,
    detect_change_order_inflation,
    detect_split_tendering,
    detect_vendor_concentration_capture,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_detect_split_tendering_flags_repeated_near_threshold_awards():
    end = _now()
    start = end - timedelta(days=30)
    rows = [
        {
            "tender_id": "T-001",
            "vendor_id": "V-77",
            "agency": "min-finance",
            "sector": "public",
            "amount": 910000.0,
            "project_id": "P-1",
        },
        {
            "tender_id": "T-002",
            "vendor_id": "V-77",
            "agency": "min-finance",
            "sector": "public",
            "amount": 930000.0,
            "project_id": "P-2",
        },
        {
            "tender_id": "T-003",
            "vendor_id": "V-77",
            "agency": "min-finance",
            "sector": "public",
            "amount": 890000.0,
            "project_id": "P-3",
        },
    ]
    out = detect_split_tendering(rows, window_start=start, window_end=end)
    assert len(out) == 1
    alert = out[0]
    assert alert.detector_type == "split_tendering"
    assert alert.vendor_id == "V-77"
    assert alert.score >= 0.55
    assert "split_tender_pattern" in alert.reason_codes


def test_detect_vendor_concentration_capture_flags_high_share_vendor():
    end = _now()
    start = end - timedelta(days=30)
    rows = [
        {"tender_id": "T1", "vendor_id": "V-10", "agency": "moh", "sector": "health", "amount": 1_300_000.0},
        {"tender_id": "T2", "vendor_id": "V-10", "agency": "moh", "sector": "health", "amount": 1_200_000.0},
        {"tender_id": "T3", "vendor_id": "V-10", "agency": "moh", "sector": "health", "amount": 1_250_000.0},
        {"tender_id": "T4", "vendor_id": "V-22", "agency": "moh", "sector": "health", "amount": 400_000.0},
    ]
    out = detect_vendor_concentration_capture(rows, window_start=start, window_end=end)
    assert len(out) >= 1
    top = out[0]
    assert top.detector_type == "vendor_concentration"
    assert top.vendor_id == "V-10"
    assert top.indicators["amount_share"] >= 0.45


def test_detect_change_order_inflation_flags_repeat_inflated_records():
    end = _now()
    start = end - timedelta(days=30)
    rows = [
        {
            "tender_id": "C-1",
            "vendor_id": "V-88",
            "agency": "roads",
            "sector": "infrastructure",
            "amount": 2_000_000.0,
            "baseline_amount": 1_200_000.0,
            "change_order_count": 3,
            "project_id": "R1",
        },
        {
            "tender_id": "C-2",
            "vendor_id": "V-88",
            "agency": "roads",
            "sector": "infrastructure",
            "amount": 1_900_000.0,
            "baseline_amount": 1_300_000.0,
            "change_order_count": 2,
            "project_id": "R2",
        },
    ]
    out = detect_change_order_inflation(rows, window_start=start, window_end=end)
    assert len(out) == 1
    alert = out[0]
    assert alert.detector_type == "change_order_inflation"
    assert alert.score >= 0.5
    assert alert.indicators["records_flagged"] == 2


def test_detect_bid_rotation_ring_flags_stable_rotation_pattern():
    end = _now()
    start = end - timedelta(days=30)
    rows = []
    vendors = ["V-A", "V-B", "V-C", "V-A", "V-B", "V-C", "V-A", "V-B", "V-C"]
    for idx, vendor in enumerate(vendors):
        rows.append(
            {
                "tender_id": f"BR-{idx+1}",
                "vendor_id": vendor,
                "agency": "county-health-x",
                "sector": "health",
                "amount": 450_000.0 + (idx * 2_500.0),
                "occurred_at": start + timedelta(days=idx),
            }
        )

    out = detect_bid_rotation_ring(rows, window_start=start, window_end=end)
    assert len(out) == 1
    alert = out[0]
    assert alert.detector_type == "bid_rotation_ring"
    assert alert.agency == "county-health-x"
    assert alert.indicators["rotation_ratio"] >= 0.8
