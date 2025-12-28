from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.ingestion.schemas import CanonicalEvent
from app.graph.ontology import (
    NodeRef,
    GraphNode,
    GraphEdge,
    make_node,
    make_edge,
    dedupe_nodes,
    dedupe_edges,
)

# ============================================================
# Helpers (defensive normalization)
# ============================================================

def _get_anchor(event: CanonicalEvent, name: str) -> Optional[str]:
    v = (event.anchors or {}).get(name)
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return str(v).strip()


def _get_payload(event: CanonicalEvent, name: str) -> Optional[str]:
    v = (event.payload or {}).get(name)
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return str(v).strip()


def _strip_repeated_prefix(prefix: str, value: Optional[str]) -> Optional[str]:
    """
    Convert values that may be sent as raw or already-prefixed to a RAW id.
    Examples:
      value="demo1"                 -> "demo1"
      value="person_h:demo1"        -> "demo1"
      value="person_h:person_h:x"   -> "x"
    """
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None

    p = f"{prefix}:"
    while v.startswith(p):
        v = v[len(p):].strip()

    return v or None


def _norm_key(prefix: str, value: Optional[str]) -> Optional[str]:
    """
    Normalize to a SINGLE prefixed key.
    Examples:
      value="demo1"                -> "person_h:demo1"
      value="person_h:demo1"       -> "person_h:demo1"
      value="person_h:person_h:x"  -> "person_h:x"
    """
    raw = _strip_repeated_prefix(prefix, value)
    if not raw:
        return None
    return f"{prefix}:{raw}"


def _add_minimal_indicator_nodes(
    *,
    nodes: list[GraphNode],
    ip: Optional[str],
    domain: Optional[str],
    url: Optional[str],
) -> None:
    """
    MVP policy: always emit at least indicator nodes when present.
    Ensures IP-only events still produce a meaningful delta.
    """
    if ip:
        nodes.append(make_node(NodeRef("IP", ip)))
    if domain:
        nodes.append(make_node(NodeRef("Domain", domain)))
    if url:
        nodes.append(make_node(NodeRef("URL", url)))


# ============================================================
# Output
# ============================================================

@dataclass(frozen=True)
class GraphDelta:
    event_hash: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def project_event_to_delta(*, event: CanonicalEvent, event_hash: str) -> GraphDelta:
    """
    Deterministic projection: CanonicalEvent -> {nodes, edges}

    Rules:
    - deterministic mapping only (no heuristics)
    - every edge has evidence=[event_hash]
    - minimal projection always emits indicator nodes (IP/Domain/URL) if present

    Complexity: O(a) where a = anchors used
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    ev = [event_hash]

    et = (event.event_type or "").upper()

    # Common anchors (anchors take precedence, payload fallback)
    ip = _get_anchor(event, "ip") or _get_payload(event, "ip")
    domain = _get_anchor(event, "domain") or _get_payload(event, "domain")
    url = _get_anchor(event, "url") or _get_payload(event, "url")

    # Normalized hashed identifiers (always single-prefixed)
    phone_h = _norm_key("phone_h", _get_anchor(event, "phone_h"))
    person_h = _norm_key("person_h", _get_anchor(event, "person_h"))
    account_h = _norm_key("account_h", _get_anchor(event, "account_h"))

    device_id = _get_anchor(event, "device_id")
    service_id = _get_anchor(event, "service_id")
    endpoint = _get_anchor(event, "endpoint") or _get_payload(event, "endpoint")
    provider_id = _get_anchor(event, "provider_id")  # optional for now

    # Minimal indicator nodes (applies to ALL events)
    _add_minimal_indicator_nodes(nodes=nodes, ip=ip, domain=domain, url=url)

    # ============================================================
    # Event-specific projections
    # ============================================================

    if et == "LOGIN_EVENT":
        # Person -> IP, Person -> Device, IP -> Endpoint -> Service
        person_ref = NodeRef("Person", person_h) if person_h else None
        if person_ref:
            nodes.append(make_node(person_ref))

            if ip:
                ip_ref = NodeRef("IP", ip)
                edges.append(make_edge("LOGGED_IN_FROM", person_ref, ip_ref, evidence=ev))

            if device_id:
                dev_ref = NodeRef("Device", device_id)
                nodes.append(make_node(dev_ref))
                edges.append(make_edge("USED_DEVICE", person_ref, dev_ref, evidence=ev))

        if ip and endpoint:
            ip_ref = NodeRef("IP", ip)
            ep_ref = NodeRef("Endpoint", endpoint)
            nodes.append(make_node(ep_ref))
            edges.append(make_edge("ACCESSED_ENDPOINT", ip_ref, ep_ref, evidence=ev))

            if service_id:
                svc_ref = NodeRef("Service", service_id)
                nodes.append(make_node(svc_ref))
                edges.append(make_edge("PART_OF_SERVICE", ep_ref, svc_ref, evidence=ev))

    elif et == "SIM_SWAP_EVENT":
        # Phone -> Device
        phone_ref = NodeRef("Phone", phone_h) if phone_h else None
        if phone_ref:
            nodes.append(make_node(phone_ref))

            if device_id:
                dev_ref = NodeRef("Device", device_id)
                nodes.append(make_node(dev_ref))
                edges.append(make_edge("SIM_SWAPPED_TO", phone_ref, dev_ref, evidence=ev))

        # Optional: Person -> Phone
        if person_h and phone_h:
            person_ref = NodeRef("Person", person_h)
            phone_ref = NodeRef("Phone", phone_h)
            nodes.append(make_node(person_ref))
            nodes.append(make_node(phone_ref))
            edges.append(make_edge("HAS_SIM", person_ref, phone_ref, evidence=ev))

    elif et == "TRANSACTION_EVENT":
        a_from = _get_anchor(event, "account_h_from") or _get_payload(event, "account_h_from")
        a_to = _get_anchor(event, "account_h_to") or _get_payload(event, "account_h_to")

        from_key = _norm_key("account_h", a_from)
        to_key = _norm_key("account_h", a_to)

        n_from = NodeRef("Account", from_key) if from_key else None
        n_to = NodeRef("Account", to_key) if to_key else None

        if n_from:
            nodes.append(make_node(n_from))
        if n_to:
            nodes.append(make_node(n_to))
        if n_from and n_to:
            edges.append(make_edge("TRANSFERRED_TO", n_from, n_to, evidence=ev))

    elif et == "DOMAIN_REG_EVENT":
        if domain:
            d_ref = NodeRef("Domain", domain)
            nodes.append(make_node(d_ref))

            if provider_id:
                p_ref = NodeRef("Provider", provider_id)
                nodes.append(make_node(p_ref))
                edges.append(make_edge("HOSTED_ON", d_ref, p_ref, evidence=ev))

    elif et == "DNS_RESOLUTION_EVENT":
        if domain and ip:
            d_ref = NodeRef("Domain", domain)
            ip_ref = NodeRef("IP", ip)
            edges.append(make_edge("RESOLVES_TO", d_ref, ip_ref, evidence=ev))

    elif et == "PHISHING_MESSAGE_EVENT":
        # Domain/URL -> Service (if present)
        svc_ref = NodeRef("Service", service_id) if service_id else None
        if svc_ref:
            nodes.append(make_node(svc_ref))

        if domain and svc_ref:
            d_ref = NodeRef("Domain", domain)
            edges.append(make_edge("PHISHES", d_ref, svc_ref, evidence=ev))

        if url and svc_ref:
            u_ref = NodeRef("URL", url)
            edges.append(make_edge("PHISHES", u_ref, svc_ref, evidence=ev))

    elif et == "DDOS_SIGNAL_EVENT":
        # IP -> Endpoint -> Service, IP -> Provider (optional)
        if ip and endpoint:
            ip_ref = NodeRef("IP", ip)
            ep_ref = NodeRef("Endpoint", endpoint)
            nodes.append(make_node(ep_ref))
            edges.append(make_edge("TARGETS", ip_ref, ep_ref, evidence=ev))

            if service_id:
                svc_ref = NodeRef("Service", service_id)
                nodes.append(make_node(svc_ref))
                edges.append(make_edge("PART_OF_SERVICE", ep_ref, svc_ref, evidence=ev))

        if ip and provider_id:
            ip_ref = NodeRef("IP", ip)
            p_ref = NodeRef("Provider", provider_id)
            nodes.append(make_node(p_ref))
            edges.append(make_edge("USES_INFRA", ip_ref, p_ref, evidence=ev))

    elif et == "SERVICE_HEALTH_EVENT":
        # Store health metrics on Service node
        if service_id:
            svc_ref = NodeRef("Service", service_id)
            nodes.append(make_node(svc_ref, health=event.payload))

    else:
        # Unknown event types: deterministic nodes only from known anchors
        for k, v in (event.anchors or {}).items():
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue

            if k == "ip":
                ref = NodeRef("IP", s)
            elif k == "domain":
                ref = NodeRef("Domain", s)
            elif k == "url":
                ref = NodeRef("URL", s)
            elif k == "service_id":
                ref = NodeRef("Service", s)
            elif k == "endpoint":
                ref = NodeRef("Endpoint", s)
            elif k == "device_id":
                ref = NodeRef("Device", s)
            elif k == "phone_h":
                ref = NodeRef("Phone", _norm_key("phone_h", s) or s)
            elif k == "person_h":
                ref = NodeRef("Person", _norm_key("person_h", s) or s)
            elif k == "account_h":
                ref = NodeRef("Account", _norm_key("account_h", s) or s)
            elif k == "provider_id":
                ref = NodeRef("Provider", s)
            else:
                continue

            nodes.append(make_node(ref))

    return GraphDelta(
        event_hash=event_hash,
        nodes=dedupe_nodes(nodes),
        edges=dedupe_edges(edges),
    )
