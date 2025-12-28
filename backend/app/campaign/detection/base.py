from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

class DetectionResult:
    def __init__(self, *, type: str, primary_key: str, entities: list[tuple[str, str]]):
        self.type = type
        self.primary_key = primary_key
        self.entities = entities

class Detector(ABC):
    @abstractmethod
    def detect(self, *, event_hash: str, event: dict, occurred_at: datetime) -> Iterable[DetectionResult]:
        ...
