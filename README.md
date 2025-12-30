# Sentinel-KE

Sentinel-KE is a cybersecurity platform designed as a layered system for threat intelligence, focusing on ingestion, graph projection, and analysis. This README outlines the implemented layers, their purposes, guarantees, and architectures.

## Layer 1: Backend & Ingestion Layer

**Status: COMPLETE (100%)**  
**Scope: Evidence-grade ingestion, immutability, provenance, streaming, search**

### Purpose of Layer 1

Layer 1 is the **national nervous system I/O layer**.

It is responsible for:
- Accepting signals from multiple sources
- Enforcing provenance, integrity, and trust
- Persisting immutable evidence
- Publishing normalized events to downstream intelligence layers

Layer 1 **does not reason**.  
Layer 1 **does not infer**.  
Layer 1 **only guarantees truth, structure, and replayability**.

### Core Guarantees

#### G1 — Evidence Immutability
- Events are append-only
- No updates or deletes
- Deterministic `event_hash`
- Full replay supported

#### G2 — Provenance & Trust
- Every event tied to:
  - `source_id`
  - `source_type`
  - `classification`
- API-key based source registry
- Audit trail for every ingest action

#### G3 — Deterministic Idempotency
- Same canonical event → same `event_hash`
- Duplicate submissions return `status=duplicate`
- No double counting downstream

#### G4 — No Raw PII
- Pseudonymization enforced at ingest
- Only hashed anchors allowed downstream
- Graph and analytics never see raw identifiers

#### G5 — Time Sanity
- `occurred_at` validated
- Future timestamps rejected
- UTC enforced

### High-Level Architecture

```mermaid
flowchart LR
    SRC[External Source] -->|API Key| INGEST["/v1/ingest/event"]
    INGEST --> NORM[Normalize + Validate]
    NORM --> HASH[Compute event_hash]
    HASH --> LEDGER[(Postgres Ledger)]
    HASH --> OS[(OpenSearch)]
    HASH --> KAFKA[Redpanda / Kafka]
    HASH --> GRAPH[(Graph Delta Log)]
Layer 2: Infra → Graph Projection (Neo4j)
Status: ✅ COMPLETE · 🔒 LOCKED
Layer: 2 / 4
Role: Deterministic projection of InfraClusters from PostgreSQL into Neo4j
What Layer 2 Does (In One Sentence)
Layer 2 projects infrastructure clusters derived from PostgreSQL into Neo4j as a deterministic, idempotent graph, without Neo4j ever becoming a source of truth.
Architectural Position
Layer 2 sits between the ledger (Postgres) and graph intelligence (Neo4j).
mermaidflowchart LR
    A[Event Ledger<br/>PostgreSQL] --> B[Infra Clustering<br/>Layer 1]
    B --> C[Graph Projection<br/>Layer 2]
    C --> D[Neo4j Graph]
    D --> E[Investigations / UI / Analytics]

    style C fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
Sequence Diagram
mermaidsequenceDiagram
    participant API as FastAPI
    participant PG as PostgreSQL
    participant P as Infra Projector
    participant N4J as Neo4j

    API->>PG: Load InfraCluster + Members + Evidence
    PG-->>P: InfraCluster state
    P->>P: Build deterministic GraphDelta
    API->>N4J: Apply GraphDelta (MERGE)
    N4J-->>API: Acknowledged
GraphDelta Structure
PythonGraphDelta(
    event_hash: str,
    nodes: list[Node],
    edges: list[Edge]
)
Class Diagram
mermaidclassDiagram
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
Validated Edges
All edges are validated and whitelisted:

MEMBER_OF
USES_INFRA
SUPPORTED_BY
EVIDENCED_BY
TARGETS

Next Steps
When you’re ready, we’ll proceed to Layer 3 with:

Graph algorithms
Temporal reasoning
Campaign expansion
Analyst queries

…without touching a single line of Layer 2.
text**Why This Improved Version is Better**:
- **Single H1**: One top-level title for the whole project.
- **Parallel H2 for Layers**: Treats Layer 1 and Layer 2 as equal major sections.
- **Dropped Numbering in H2**: Uses descriptive titles instead (e.g., "## Purpose" instead of "## 0. Purpose") for better scannability.
- **Added H3/H4 for Subcontent**: Groups diagrams and code under subsections to avoid floating elements.
- **Consistent Flow**: Matches best practices—overview first, details nested, ends with forward-looking section.
- **GitHub Compatibility**: Will generate a clean table of contents. Mermaid fixes (e.g., quoted labels) ensure no rendering errors.

If you push this improved version to GitHub, it should render perfectly. Let me know if you need further tweaks!23s10 sources