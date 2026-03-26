from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.defense.executor import dispatch_containment_action
from app.defense.models import WebhookDelivery


def test_dispatch_containment_action_records_no_integration_delivery():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    def _add(obj):
        if isinstance(obj, WebhookDelivery) and obj.id is None:
            obj.id = uuid.uuid4()

    db.add.side_effect = _add

    status, details = dispatch_containment_action(
        db=db,
        action_type="block_ip",
        target="41.90.0.8",
        section_code="telecom",
    )

    assert status == "no_webhook"
    assert details["delivery_status"] == "no_integration"
    assert details["delivery_id"]

    delivery = next(
        obj for obj in (call.args[0] for call in db.add.call_args_list)
        if isinstance(obj, WebhookDelivery)
    )
    assert delivery.status == "no_integration"
    assert delivery.attempt_count == 0
    assert delivery.error_message == "no webhook registered for this section/action type"
    assert delivery.response_body["hint"] == "Register a webhook via POST /v1/defense/webhooks"
