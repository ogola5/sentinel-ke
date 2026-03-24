from __future__ import annotations

from scripts import demo_federation_show as demo


def test_hmac_hash_is_deterministic():
    entity = "phone:+254700123456"
    salt = "sentinel-salt"
    h1 = demo._hmac_hash(entity, salt)  # noqa: SLF001
    h2 = demo._hmac_hash(entity, salt)  # noqa: SLF001
    assert h1 == h2
    assert len(h1) == 64


def test_build_multi_agency_correlations_detects_shared_entity():
    rows, correlations = demo.build_multi_agency_correlations(
        [
            ("phone:+254700123456", "Safaricom", "SIM_SWAP", 0.91),
            ("phone:+254700123456", "CBK", "SIM_SWAP", 0.83),
            ("ip:196.201.214.55", "KE-CIRT", "VPN_FRAUD", 0.79),
        ],
        salt="national-salt",
    )

    assert len(rows) == 3
    assert len(correlations) == 1
    corr = correlations[0]
    assert corr["agencies"] == ["Safaricom", "CBK"]
    assert corr["family"] == "SIM_SWAP"
    assert corr["sources"] == 2


def test_show_multi_agency_table_prints_correlation_summary(capsys):
    demo.show_multi_agency_table(delay=False)
    out = capsys.readouterr().out
    assert "CROSS-AGENCY FEDERATION PATTERNS" in out
    assert "cross-agency correlation" in out.lower()
    assert "Safaricom, CBK" in out


def test_presenter_talking_points_avoid_hard_coded_claims():
    points = demo.presenter_talking_points()
    joined = " ".join(points)
    assert "5 million" not in joined
    assert "94%" not in joined
    assert "Use benchmark and operational-probe artifacts" in joined
