from app.analytics.layer3.cyber_relations import derive_typed_edges_for_event


def test_login_event_derives_account_device_and_ip_edges():
    out = derive_typed_edges_for_event(
        event_type="LOGIN_EVENT",
        entity_keys=[
            "account_h:acc1",
            "device_id:dev1",
            "ip:203.0.113.10",
            "endpoint:/login",
        ],
    )
    keys = {(a, b) for a, b, _ in out}
    assert ("account_h:acc1", "device_id:dev1") in keys
    assert ("account_h:acc1", "ip:203.0.113.10") in keys


def test_ddos_event_derives_service_endpoint_edge():
    out = derive_typed_edges_for_event(
        event_type="DDOS_SIGNAL_EVENT",
        entity_keys=[
            "service_id:kplc",
            "endpoint:/login",
            "ip:198.51.100.7",
        ],
    )
    assert any(
        {src, dst} == {"service_id:kplc", "endpoint:/login"}
        for src, dst, _weight in out
    )
