from datetime import datetime
from app.campaign.detection.base import Detector, DetectionResult

class DDoSDetector(Detector):
    """
    Many IPs hitting same endpoint/service.
    """

    def detect(self, *, event_hash: str, event: dict, occurred_at: datetime):
        anchors = event.get("anchors", {})
        endpoint = anchors.get("endpoint")
        ip = anchors.get("ip")

        if not endpoint or not ip:
            return []

        return [
            DetectionResult(
                type="DDOS_FANIN",
                primary_key=f"endpoint:{endpoint}",
                entities=[
                    ("Endpoint", f"endpoint:{endpoint}"),
                    ("IP", f"ip:{ip}"),
                ],
            )
        ]
