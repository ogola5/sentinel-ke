# backend/app/analytics/infra_similarity.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Optional

from opensearchpy import OpenSearch


@dataclass
class IPProfile:
    ip: str
    endpoints: Set[str]
    services: Set[str]
    domains: Set[str]
    providers: Set[str]  # if present in anchors
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    event_count: int = 0


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a.intersection(b))
    if inter == 0:
        return 0.0
    union = len(a.union(b))
    return inter / union if union else 0.0


def ip_prefix24(ip: str) -> str:
    # very light heuristic for MVP when provider/asn is missing
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return "unknown"


def fetch_ip_profiles(
    client: OpenSearch,
    index: str,
    time_range: dict,
    max_ips: int = 200,
    per_ip_terms: int = 30,
) -> Dict[str, IPProfile]:
    """
    Builds lightweight per-IP profiles using OpenSearch aggregations.

    Assumes anchors.* fields are aggregatable (your existing infra.py uses cardinality on anchors.*).
    """
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"occurred_at": time_range}},
                    {"exists": {"field": "anchors.ip"}},
                ]
            }
        },
        "aggs": {
            "ips": {
                "terms": {"field": "anchors.ip.keyword", "size": max_ips},
                "aggs": {
                    "endpoints": {"terms": {"field": "anchors.endpoint_id", "size": per_ip_terms}},
                    "services": {"terms": {"field": "anchors.service_id.keyword", "size": per_ip_terms}},
                    "domains": {"terms": {"field": "anchors.domain", "size": per_ip_terms}},
                    "providers": {"terms": {"field": "anchors.provider_id", "size": per_ip_terms}},
                    "first_seen": {"min": {"field": "occurred_at"}},
                    "last_seen": {"max": {"field": "occurred_at"}},
                },
            }
        },
    }

    res = client.search(index=index, body=body)
    buckets = res.get("aggregations", {}).get("ips", {}).get("buckets", [])

    out: Dict[str, IPProfile] = {}
    for b in buckets:
        ip = b.get("key")
        if not ip:
            continue
        out[ip] = IPProfile(
            ip=ip,
            endpoints={x["key"] for x in b.get("endpoints", {}).get("buckets", []) if x.get("key")},
            services={x["key"] for x in b.get("services", {}).get("buckets", []) if x.get("key")},
            domains={x["key"] for x in b.get("domains", {}).get("buckets", []) if x.get("key")},
            providers={x["key"] for x in b.get("providers", {}).get("buckets", []) if x.get("key")},
            first_seen=(b.get("first_seen", {}) or {}).get("value_as_string"),
            last_seen=(b.get("last_seen", {}) or {}).get("value_as_string"),
            event_count=int(b.get("doc_count") or 0),
        )
    return out


class UnionFind:
    def __init__(self, items: List[str]):
        self.parent = {x: x for x in items}
        self.rank = {x: 0 for x in items}

    def find(self, x: str) -> str:
        p = self.parent.get(x, x)
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent.get(x, x)

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def build_clusters(
    profiles: Dict[str, IPProfile],
    min_endpoint_jaccard: float = 0.35,
    min_service_jaccard: float = 0.35,
    require_any_overlap: bool = True,
) -> Tuple[List[List[str]], List[dict]]:
    """
    Returns:
      clusters: list of ip lists
      evidence: list of edge-level evidence objects for later summarization

    Complexity: O(n^2) on number of IPs in window (n <= max_ips).
    For MVP windows this is fine; keep max_ips <= 200.
    """
    ips = list(profiles.keys())
    uf = UnionFind(ips)
    evidence_edges: List[dict] = []

    n = len(ips)
    for i in range(n):
        a = profiles[ips[i]]
        for j in range(i + 1, n):
            b = profiles[ips[j]]

            ep_j = jaccard(a.endpoints, b.endpoints)
            sv_j = jaccard(a.services, b.services)

            linked = (ep_j >= min_endpoint_jaccard) or (sv_j >= min_service_jaccard)
            if require_any_overlap and not linked:
                # fallback: if both missing, allow prefix heuristic only when both share nothing else
                if not a.providers and not b.providers:
                    if ip_prefix24(a.ip) == ip_prefix24(b.ip) and (a.endpoints or a.services) and (b.endpoints or b.services):
                        linked = True
                        evidence_edges.append({
                            "a": a.ip, "b": b.ip,
                            "reason_code": "PREFIX_HEURISTIC",
                            "score": 0.2,
                            "details": {"prefix": ip_prefix24(a.ip)},
                        })
                continue

            if linked:
                uf.union(a.ip, b.ip)
                details = {
                    "endpoint_jaccard": ep_j,
                    "service_jaccard": sv_j,
                    "shared_endpoints": sorted(list(a.endpoints.intersection(b.endpoints)))[:10],
                    "shared_services": sorted(list(a.services.intersection(b.services)))[:10],
                }
                evidence_edges.append({
                    "a": a.ip, "b": b.ip,
                    "reason_code": "ENDPOINT_OVERLAP" if ep_j >= sv_j else "SERVICE_OVERLAP",
                    "score": max(ep_j, sv_j),
                    "details": details,
                })

    groups: Dict[str, List[str]] = {}
    for ip in ips:
        r = uf.find(ip)
        groups.setdefault(r, []).append(ip)

    clusters = [sorted(v) for v in groups.values() if len(v) >= 2]
    clusters.sort(key=len, reverse=True)
    return clusters, evidence_edges
