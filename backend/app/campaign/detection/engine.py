from datetime import datetime
from app.campaign.detection.infra_reuse import InfraReuseDetector
from app.campaign.detection.ddos import DDoSDetector

DETECTORS = [
    InfraReuseDetector(),
    DDoSDetector(),
]

def run_detectors(*, event_hash: str, event: dict, occurred_at: datetime):
    for d in DETECTORS:
        for r in d.detect(event_hash=event_hash, event=event, occurred_at=occurred_at):
            yield r
