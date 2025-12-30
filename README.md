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
#mermaid-diagram-mermaid-cdkz3bx{font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:16px;fill:#ccc;}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#mermaid-diagram-mermaid-cdkz3bx .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#mermaid-diagram-mermaid-cdkz3bx .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#mermaid-diagram-mermaid-cdkz3bx .error-icon{fill:#a44141;}#mermaid-diagram-mermaid-cdkz3bx .error-text{fill:#ddd;stroke:#ddd;}#mermaid-diagram-mermaid-cdkz3bx .edge-thickness-normal{stroke-width:1px;}#mermaid-diagram-mermaid-cdkz3bx .edge-thickness-thick{stroke-width:3.5px;}#mermaid-diagram-mermaid-cdkz3bx .edge-pattern-solid{stroke-dasharray:0;}#mermaid-diagram-mermaid-cdkz3bx .edge-thickness-invisible{stroke-width:0;fill:none;}#mermaid-diagram-mermaid-cdkz3bx .edge-pattern-dashed{stroke-dasharray:3;}#mermaid-diagram-mermaid-cdkz3bx .edge-pattern-dotted{stroke-dasharray:2;}#mermaid-diagram-mermaid-cdkz3bx .marker{fill:lightgrey;stroke:lightgrey;}#mermaid-diagram-mermaid-cdkz3bx .marker.cross{stroke:lightgrey;}#mermaid-diagram-mermaid-cdkz3bx svg{font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:16px;}#mermaid-diagram-mermaid-cdkz3bx p{margin:0;}#mermaid-diagram-mermaid-cdkz3bx .label{font-family:"trebuchet ms",verdana,arial,sans-serif;color:#ccc;}#mermaid-diagram-mermaid-cdkz3bx .cluster-label text{fill:#F9FFFE;}#mermaid-diagram-mermaid-cdkz3bx .cluster-label span{color:#F9FFFE;}#mermaid-diagram-mermaid-cdkz3bx .cluster-label span p{background-color:transparent;}#mermaid-diagram-mermaid-cdkz3bx .label text,#mermaid-diagram-mermaid-cdkz3bx span{fill:#ccc;color:#ccc;}#mermaid-diagram-mermaid-cdkz3bx .node rect,#mermaid-diagram-mermaid-cdkz3bx .node circle,#mermaid-diagram-mermaid-cdkz3bx .node ellipse,#mermaid-diagram-mermaid-cdkz3bx .node polygon,#mermaid-diagram-mermaid-cdkz3bx .node path{fill:#1f2020;stroke:#ccc;stroke-width:1px;}#mermaid-diagram-mermaid-cdkz3bx .rough-node .label text,#mermaid-diagram-mermaid-cdkz3bx .node .label text,#mermaid-diagram-mermaid-cdkz3bx .image-shape .label,#mermaid-diagram-mermaid-cdkz3bx .icon-shape .label{text-anchor:middle;}#mermaid-diagram-mermaid-cdkz3bx .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#mermaid-diagram-mermaid-cdkz3bx .rough-node .label,#mermaid-diagram-mermaid-cdkz3bx .node .label,#mermaid-diagram-mermaid-cdkz3bx .image-shape .label,#mermaid-diagram-mermaid-cdkz3bx .icon-shape .label{text-align:center;}#mermaid-diagram-mermaid-cdkz3bx .node.clickable{cursor:pointer;}#mermaid-diagram-mermaid-cdkz3bx .root .anchor path{fill:lightgrey!important;stroke-width:0;stroke:lightgrey;}#mermaid-diagram-mermaid-cdkz3bx .arrowheadPath{fill:lightgrey;}#mermaid-diagram-mermaid-cdkz3bx .edgePath .path{stroke:lightgrey;stroke-width:2.0px;}#mermaid-diagram-mermaid-cdkz3bx .flowchart-link{stroke:lightgrey;fill:none;}#mermaid-diagram-mermaid-cdkz3bx .edgeLabel{background-color:hsl(0, 0%, 34.4117647059%);text-align:center;}#mermaid-diagram-mermaid-cdkz3bx .edgeLabel p{background-color:hsl(0, 0%, 34.4117647059%);}#mermaid-diagram-mermaid-cdkz3bx .edgeLabel rect{opacity:0.5;background-color:hsl(0, 0%, 34.4117647059%);fill:hsl(0, 0%, 34.4117647059%);}#mermaid-diagram-mermaid-cdkz3bx .labelBkg{background-color:rgba(87.75, 87.75, 87.75, 0.5);}#mermaid-diagram-mermaid-cdkz3bx .cluster rect{fill:hsl(180, 1.5873015873%, 28.3529411765%);stroke:rgba(255, 255, 255, 0.25);stroke-width:1px;}#mermaid-diagram-mermaid-cdkz3bx .cluster text{fill:#F9FFFE;}#mermaid-diagram-mermaid-cdkz3bx .cluster span{color:#F9FFFE;}#mermaid-diagram-mermaid-cdkz3bx div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:12px;background:hsl(20, 1.5873015873%, 12.3529411765%);border:1px solid rgba(255, 255, 255, 0.25);border-radius:2px;pointer-events:none;z-index:100;}#mermaid-diagram-mermaid-cdkz3bx .flowchartTitleText{text-anchor:middle;font-size:18px;fill:#ccc;}#mermaid-diagram-mermaid-cdkz3bx rect.text{fill:none;stroke-width:0;}#mermaid-diagram-mermaid-cdkz3bx .icon-shape,#mermaid-diagram-mermaid-cdkz3bx .image-shape{background-color:hsl(0, 0%, 34.4117647059%);text-align:center;}#mermaid-diagram-mermaid-cdkz3bx .icon-shape p,#mermaid-diagram-mermaid-cdkz3bx .image-shape p{background-color:hsl(0, 0%, 34.4117647059%);padding:2px;}#mermaid-diagram-mermaid-cdkz3bx .icon-shape rect,#mermaid-diagram-mermaid-cdkz3bx .image-shape rect{opacity:0.5;background-color:hsl(0, 0%, 34.4117647059%);fill:hsl(0, 0%, 34.4117647059%);}#mermaid-diagram-mermaid-cdkz3bx :root{--mermaid-font-family:"trebuchet ms",verdana,arial,sans-serif;}Event Ledger
PostgreSQLInfra Clustering
Layer 1Graph Projection
Layer 2Neo4j GraphInvestigations / UI / Analytics
Sequence Diagram
Neo4jInfra ProjectorPostgreSQLFastAPINeo4jInfra ProjectorPostgreSQLFastAPI#mermaid-diagram-mermaid-lgs32b6{font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:16px;fill:#ccc;}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#mermaid-diagram-mermaid-lgs32b6 .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#mermaid-diagram-mermaid-lgs32b6 .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#mermaid-diagram-mermaid-lgs32b6 .error-icon{fill:#a44141;}#mermaid-diagram-mermaid-lgs32b6 .error-text{fill:#ddd;stroke:#ddd;}#mermaid-diagram-mermaid-lgs32b6 .edge-thickness-normal{stroke-width:1px;}#mermaid-diagram-mermaid-lgs32b6 .edge-thickness-thick{stroke-width:3.5px;}#mermaid-diagram-mermaid-lgs32b6 .edge-pattern-solid{stroke-dasharray:0;}#mermaid-diagram-mermaid-lgs32b6 .edge-thickness-invisible{stroke-width:0;fill:none;}#mermaid-diagram-mermaid-lgs32b6 .edge-pattern-dashed{stroke-dasharray:3;}#mermaid-diagram-mermaid-lgs32b6 .edge-pattern-dotted{stroke-dasharray:2;}#mermaid-diagram-mermaid-lgs32b6 .marker{fill:lightgrey;stroke:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 .marker.cross{stroke:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 svg{font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:16px;}#mermaid-diagram-mermaid-lgs32b6 p{margin:0;}#mermaid-diagram-mermaid-lgs32b6 .actor{stroke:#ccc;fill:#1f2020;}#mermaid-diagram-mermaid-lgs32b6 text.actor>tspan{fill:lightgrey;stroke:none;}#mermaid-diagram-mermaid-lgs32b6 .actor-line{stroke:#ccc;}#mermaid-diagram-mermaid-lgs32b6 .messageLine0{stroke-width:1.5;stroke-dasharray:none;stroke:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 .messageLine1{stroke-width:1.5;stroke-dasharray:2,2;stroke:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 #arrowhead path{fill:lightgrey;stroke:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 .sequenceNumber{fill:black;}#mermaid-diagram-mermaid-lgs32b6 #sequencenumber{fill:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 #crosshead path{fill:lightgrey;stroke:lightgrey;}#mermaid-diagram-mermaid-lgs32b6 .messageText{fill:lightgrey;stroke:none;}#mermaid-diagram-mermaid-lgs32b6 .labelBox{stroke:#ccc;fill:#1f2020;}#mermaid-diagram-mermaid-lgs32b6 .labelText,#mermaid-diagram-mermaid-lgs32b6 .labelText>tspan{fill:lightgrey;stroke:none;}#mermaid-diagram-mermaid-lgs32b6 .loopText,#mermaid-diagram-mermaid-lgs32b6 .loopText>tspan{fill:lightgrey;stroke:none;}#mermaid-diagram-mermaid-lgs32b6 .loopLine{stroke-width:2px;stroke-dasharray:2,2;stroke:#ccc;fill:#ccc;}#mermaid-diagram-mermaid-lgs32b6 .note{stroke:hsl(180, 0%, 18.3529411765%);fill:hsl(180, 1.5873015873%, 28.3529411765%);}#mermaid-diagram-mermaid-lgs32b6 .noteText,#mermaid-diagram-mermaid-lgs32b6 .noteText>tspan{fill:rgb(183.8476190475, 181.5523809523, 181.5523809523);stroke:none;}#mermaid-diagram-mermaid-lgs32b6 .activation0{fill:hsl(180, 1.5873015873%, 28.3529411765%);stroke:#ccc;}#mermaid-diagram-mermaid-lgs32b6 .activation1{fill:hsl(180, 1.5873015873%, 28.3529411765%);stroke:#ccc;}#mermaid-diagram-mermaid-lgs32b6 .activation2{fill:hsl(180, 1.5873015873%, 28.3529411765%);stroke:#ccc;}#mermaid-diagram-mermaid-lgs32b6 .actorPopupMenu{position:absolute;}#mermaid-diagram-mermaid-lgs32b6 .actorPopupMenuPanel{position:absolute;fill:#1f2020;box-shadow:0px 8px 16px 0px rgba(0,0,0,0.2);filter:drop-shadow(3px 5px 2px rgb(0 0 0 / 0.4));}#mermaid-diagram-mermaid-lgs32b6 .actor-man line{stroke:#ccc;fill:#1f2020;}#mermaid-diagram-mermaid-lgs32b6 .actor-man circle,#mermaid-diagram-mermaid-lgs32b6 line{stroke:#ccc;fill:#1f2020;stroke-width:2px;}#mermaid-diagram-mermaid-lgs32b6 :root{--mermaid-font-family:"trebuchet ms",verdana,arial,sans-serif;}Load InfraCluster + Members + EvidenceInfraCluster stateBuild deterministic GraphDeltaApply GraphDelta (MERGE)Acknowledged
GraphDelta Structure
PythonGraphDelta(
    event_hash: str,
    nodes: list[Node],
    edges: list[Edge]
)
Class Diagram
#mermaid-diagram-mermaid-iytft4u{font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:16px;fill:#ccc;}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#mermaid-diagram-mermaid-iytft4u .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#mermaid-diagram-mermaid-iytft4u .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#mermaid-diagram-mermaid-iytft4u .error-icon{fill:#a44141;}#mermaid-diagram-mermaid-iytft4u .error-text{fill:#ddd;stroke:#ddd;}#mermaid-diagram-mermaid-iytft4u .edge-thickness-normal{stroke-width:1px;}#mermaid-diagram-mermaid-iytft4u .edge-thickness-thick{stroke-width:3.5px;}#mermaid-diagram-mermaid-iytft4u .edge-pattern-solid{stroke-dasharray:0;}#mermaid-diagram-mermaid-iytft4u .edge-thickness-invisible{stroke-width:0;fill:none;}#mermaid-diagram-mermaid-iytft4u .edge-pattern-dashed{stroke-dasharray:3;}#mermaid-diagram-mermaid-iytft4u .edge-pattern-dotted{stroke-dasharray:2;}#mermaid-diagram-mermaid-iytft4u .marker{fill:lightgrey;stroke:lightgrey;}#mermaid-diagram-mermaid-iytft4u .marker.cross{stroke:lightgrey;}#mermaid-diagram-mermaid-iytft4u svg{font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:16px;}#mermaid-diagram-mermaid-iytft4u p{margin:0;}#mermaid-diagram-mermaid-iytft4u g.classGroup text{fill:#ccc;stroke:none;font-family:"trebuchet ms",verdana,arial,sans-serif;font-size:10px;}#mermaid-diagram-mermaid-iytft4u g.classGroup text .title{font-weight:bolder;}#mermaid-diagram-mermaid-iytft4u .nodeLabel,#mermaid-diagram-mermaid-iytft4u .edgeLabel{color:#e0dfdf;}#mermaid-diagram-mermaid-iytft4u .edgeLabel .label rect{fill:#1f2020;}#mermaid-diagram-mermaid-iytft4u .label text{fill:#e0dfdf;}#mermaid-diagram-mermaid-iytft4u .labelBkg{background:#1f2020;}#mermaid-diagram-mermaid-iytft4u .edgeLabel .label span{background:#1f2020;}#mermaid-diagram-mermaid-iytft4u .classTitle{font-weight:bolder;}#mermaid-diagram-mermaid-iytft4u .node rect,#mermaid-diagram-mermaid-iytft4u .node circle,#mermaid-diagram-mermaid-iytft4u .node ellipse,#mermaid-diagram-mermaid-iytft4u .node polygon,#mermaid-diagram-mermaid-iytft4u .node path{fill:#1f2020;stroke:#ccc;stroke-width:1px;}#mermaid-diagram-mermaid-iytft4u .divider{stroke:#ccc;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u g.clickable{cursor:pointer;}#mermaid-diagram-mermaid-iytft4u g.classGroup rect{fill:#1f2020;stroke:#ccc;}#mermaid-diagram-mermaid-iytft4u g.classGroup line{stroke:#ccc;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u .classLabel .box{stroke:none;stroke-width:0;fill:#1f2020;opacity:0.5;}#mermaid-diagram-mermaid-iytft4u .classLabel .label{fill:#ccc;font-size:10px;}#mermaid-diagram-mermaid-iytft4u .relation{stroke:lightgrey;stroke-width:1;fill:none;}#mermaid-diagram-mermaid-iytft4u .dashed-line{stroke-dasharray:3;}#mermaid-diagram-mermaid-iytft4u .dotted-line{stroke-dasharray:1 2;}#mermaid-diagram-mermaid-iytft4u #compositionStart,#mermaid-diagram-mermaid-iytft4u .composition{fill:lightgrey!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #compositionEnd,#mermaid-diagram-mermaid-iytft4u .composition{fill:lightgrey!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #dependencyStart,#mermaid-diagram-mermaid-iytft4u .dependency{fill:lightgrey!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #dependencyStart,#mermaid-diagram-mermaid-iytft4u .dependency{fill:lightgrey!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #extensionStart,#mermaid-diagram-mermaid-iytft4u .extension{fill:transparent!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #extensionEnd,#mermaid-diagram-mermaid-iytft4u .extension{fill:transparent!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #aggregationStart,#mermaid-diagram-mermaid-iytft4u .aggregation{fill:transparent!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #aggregationEnd,#mermaid-diagram-mermaid-iytft4u .aggregation{fill:transparent!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #lollipopStart,#mermaid-diagram-mermaid-iytft4u .lollipop{fill:#1f2020!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u #lollipopEnd,#mermaid-diagram-mermaid-iytft4u .lollipop{fill:#1f2020!important;stroke:lightgrey!important;stroke-width:1;}#mermaid-diagram-mermaid-iytft4u .edgeTerminals{font-size:11px;line-height:initial;}#mermaid-diagram-mermaid-iytft4u .classTitleText{text-anchor:middle;font-size:18px;fill:#ccc;}#mermaid-diagram-mermaid-iytft4u :root{--mermaid-font-family:"trebuchet ms",verdana,arial,sans-serif;}MEMBER_OFInfraClusterkey: cluster_idkindconfidencemember_countIPkey: ip_address
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
textAfter pushing this, the diagram should render correctly. If the error persists, check for extra spaces around the ```mermaid fences or test the Mermaid code in isolation using tools like the Mermaid Live Editor[](https://mermaid.live).17.4s12 sources