-- Materialized graph tables for query surfacing (projection)
CREATE TABLE IF NOT EXISTS graph_node (
  node_key           TEXT PRIMARY KEY,            -- entity_key or campaign:<uuid> or infra:<uuid>
  node_type          TEXT NOT NULL,               -- IP|Domain|Campaign|InfraCluster|...
  first_seen         TIMESTAMPTZ,
  last_seen          TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_graph_node_last_seen ON graph_node(last_seen);

CREATE TABLE IF NOT EXISTS graph_edge (
  edge_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  src_key            TEXT NOT NULL,
  dst_key            TEXT NOT NULL,
  edge_type          TEXT NOT NULL,               -- TARGETS|INVOLVES|INCLUDES|USES_INFRA|...
  first_seen         TIMESTAMPTZ,
  last_seen          TIMESTAMPTZ,
  count              INT NOT NULL DEFAULT 0,
  last_event_hash    TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (src_key, dst_key, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_graph_edge_src ON graph_edge(src_key);
CREATE INDEX IF NOT EXISTS idx_graph_edge_dst ON graph_edge(dst_key);
CREATE INDEX IF NOT EXISTS idx_graph_edge_type ON graph_edge(edge_type);

-- Edge -> explanation pointers
CREATE TABLE IF NOT EXISTS graph_edge_explanation (
  edge_id            UUID NOT NULL REFERENCES graph_edge(edge_id) ON DELETE CASCADE,
  explanation_id     UUID NOT NULL REFERENCES explanation(explanation_id) ON DELETE CASCADE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (edge_id, explanation_id)
);
