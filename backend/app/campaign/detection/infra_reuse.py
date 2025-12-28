from datetime import datetime
from app.campaign.detection.base import Detector, DetectionResult

class InfraReuseDetector(Detector):
    """
    IP reused across multiple persons/devices → VPN / shared infra.
    """

    def detect(self, *, event_hash: str, event: dict, occurred_at: datetime):
        anchors = event.get("anchors", {})
        ip = anchors.get("ip")
        if not ip:
            return []

        entities = [("IP", f"ip:{ip}")]

        if anchors.get("person_h"):
            entities.append(("Person", f"person_h:{anchors['person_h']}"))
        if anchors.get("device_id"):
            entities.append(("Device", f"device_id:{anchors['device_id']}"))

        return [
            DetectionResult(
                type="INFRA_REUSE",
                primary_key=f"ip:{ip}",
                entities=entities,
            )
        ]
