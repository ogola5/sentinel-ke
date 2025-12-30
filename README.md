# sentinel-ke
# Sentinel-KE — Layer 1 (Backend & Ingestion Layer)
**Status: COMPLETE (100%)**  
**Scope: Evidence-grade ingestion, immutability, provenance, streaming, search**

---

## 0. Purpose of Layer 1

Layer 1 is the **national nervous system I/O layer**.

It is responsible for:
- Accepting signals from multiple sources
- Enforcing provenance, integrity, and trust
- Persisting immutable evidence
- Publishing normalized events to downstream intelligence layers

Layer 1 **does not reason**.  
Layer 1 **does not infer**.  
Layer 1 **only guarantees truth, structure, and replayability**.

---

## 1. Core Guarantees (What Layer 1 Enforces)

### G1 — Evidence Immutability
- Events are append-only
- No updates or deletes
- Deterministic `event_hash`
- Full replay supported

### G2 — Provenance & Trust
- Every event tied to:
  - `source_id`
  - `source_type`
  - `classification`
- API-key based source registry
- Audit trail for every ingest action

### G3 — Deterministic Idempotency
- Same canonical event → same `event_hash`
- Duplicate submissions return `status=duplicate`
- No double counting downstream

### G4 — No Raw PII
- Pseudonymization enforced at ingest
- Only hashed anchors allowed downstream
- Graph and analytics never see raw identifiers

### G5 — Time Sanity
- `occurred_at` validated
- Future timestamps rejected
- UTC enforced

---

## 2. High-Level Architecture

```mermaid
flowchart LR
    SRC[External Source] -->|API Key| INGEST[/v1/ingest/event]
    INGEST --> NORM[Normalize + Validate]
    NORM --> HASH[Compute event_hash]
    HASH --> LEDGER[(Postgres Ledger)]
    HASH --> OS[(OpenSearch)]
    HASH --> KAFKA[Redpanda / Kafka]
    HASH --> GRAPH[(Graph Delta Log)]

# 🔗 Layer 2 — Infra → Graph Projection (Neo4j)

**Status:** ✅ COMPLETE · 🔒 LOCKED  
**Layer:** 2 / 4  
**Role:** Deterministic projection of InfraClusters from PostgreSQL into Neo4j

---

## 1. What Layer 2 Does (In One Sentence)

Layer 2 **projects infrastructure clusters derived from PostgreSQL into Neo4j as a deterministic, idempotent graph**, without Neo4j ever becoming a source of truth.

---

## 2. Architectural Position

Layer 2 sits **between the ledger (Postgres)** and **graph intelligence (Neo4j)**.

```mermaid
flowchart LR
    A[Event Ledger<br/>PostgreSQL] --> B[Infra Clustering<br/>Layer 1]
    B --> C[Graph Projection<br/>Layer 2]
    C --> D[Neo4j Graph]
    D --> E[Investigations / UI / Analytics]

    style C fill:#e3f2fd,stroke:#1565c0,stroke-width:2px


sequenceDiagram
    participant API as FastAPI
    participant PG as PostgreSQL
    participant P as Infra Projector
    participant N4J as Neo4j

    API->>PG: Load InfraCluster + Members + Evidence
    PG-->>P: InfraCluster state
    P->>P: Build deterministic GraphDelta
    API->>N4J: Apply GraphDelta (MERGE)
    N4J-->>API: Acknowledged


GraphDelta(
    event_hash: str,
    nodes: list[Node],
    edges: list[Edge]
)

classDiagram
    class InfraCluster {
        key: cluster_id
        kind
        confidence
        member_count
    }

    class IP {
        key: ip_address
    }

    IP --> InfraCluster : MEMBER_OF


All edges are validated and whitelisted:
MEMBER_OF
USES_INFRA
SUPPORTED_BY
EVIDENCED_BY
TARGETS


---

### Next time
When you’re ready, we’ll proceed to **Layer 3** with:
- Graph algorithms
- Temporal reasoning
- Campaign expansion
- Analyst queries

…without touching a single line of Layer 2.
