import hashlib
import json
from typing import Dict


def hash_packet(packet: Dict) -> Dict:
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    h = hashlib.sha256(raw).hexdigest()
    return {
        "hash": f"sha256:{h}",
        "hash_algo": "SHA-256",
    }
