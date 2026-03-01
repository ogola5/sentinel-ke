from app.analytics.layer3.auto_containment_worker import _entity_parts, _is_global_ip, _select_action


def test_entity_parts_splits_prefix_and_value():
    prefix, value = _entity_parts("ip:1.2.3.4", "ip")
    assert prefix == "ip"
    assert value == "1.2.3.4"


def test_select_action_for_ip_prefers_block_ip():
    out = _select_action(
        entity_key="ip:41.90.0.1",
        entity_type="ip",
        allowed_actions=["block_ip", "isolate_host"],
    )
    assert out == ("block_ip", "41.90.0.1")


def test_select_action_for_service_prefers_isolate_host():
    out = _select_action(
        entity_key="service_id:safaricom-mpesa",
        entity_type="service_id",
        allowed_actions=["isolate_host"],
    )
    assert out == ("isolate_host", "service_id:safaricom-mpesa")


def test_select_action_returns_none_when_not_allowed():
    out = _select_action(
        entity_key="ip:41.90.0.1",
        entity_type="ip",
        allowed_actions=["isolate_host"],
    )
    assert out is None


def test_select_action_rejects_private_ip_auto_block():
    out = _select_action(
        entity_key="ip:10.0.0.5",
        entity_type="ip",
        allowed_actions=["block_ip"],
    )
    assert out is None


def test_is_global_ip_validates_routable_addresses():
    assert _is_global_ip("41.90.0.1") is True
    assert _is_global_ip("127.0.0.1") is False
    assert _is_global_ip("192.168.1.1") is False
