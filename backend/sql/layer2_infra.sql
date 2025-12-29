-- InfraCluster: persistent infrastructure identity (projection object)
CREATE TABLE IF NOT EXISTS infra_cluster (
  cluster_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cluster_key        TEXT NOT NULL UNIQUE,         -- deterministic reuse key
  kind               TEXT NOT NULL,                -- ddos|vpn_exit|phishing|mule
  title              TEXT NOT NULL,
  description        TEXT,
  status             TEXT NOT NULL DEFAULT 'active',
  confidence         NUMERIC(10,4) NOT NULL DEFAULT 0, -- Layer-3 may update; Layer-2 can set 0
  first_seen         TIMESTAMPTZ NOT NULL,
  last_seen          TIMESTAMPTZ NOT NULL,
  member_count       INT NOT NULL DEFAULT 0,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_infra_cluster_kind ON infra_cluster(kind);
CREATE INDEX IF NOT EXISTS idx_infra_cluster_last_seen ON infra_cluster(last_seen);

-- Members: entity_key belongs to infra cluster
CREATE TABLE IF NOT EXISTS infra_cluster_member (
  cluster_id         UUID NOT NULL REFERENCES infra_cluster(cluster_id) ON DELETE CASCADE,
  entity_key         TEXT NOT NULL,                -- ip:.. domain:.. provider:..
  role               TEXT NOT NULL DEFAULT 'member',
  first_seen         TIMESTAMPTZ NOT NULL,
  last_seen          TIMESTAMPTZ NOT NULL,
  count              INT NOT NULL DEFAULT 0,
  last_event_hash    TEXT,
  PRIMARY KEY (cluster_id, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_infra_member_entity ON infra_cluster_member(entity_key);

-- Member explanation pointers (why this entity is included)
CREATE TABLE IF NOT EXISTS infra_member_explanation (
  cluster_id         UUID NOT NULL,
  entity_key         TEXT NOT NULL,
  explanation_id     UUID NOT NULL REFERENCES explanation(explanation_id) ON DELETE CASCADE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (cluster_id, entity_key, explanation_id),
  FOREIGN KEY (cluster_id, entity_key)
    REFERENCES infra_cluster_member(cluster_id, entity_key) ON DELETE CASCADE
);

-- Campaign <-> Infra linkage
CREATE TABLE IF NOT EXISTS campaign_infra_cluster (
  campaign_id        UUID NOT NULL,   -- references campaign(campaign_id) if exists
  cluster_id         UUID NOT NULL REFERENCES infra_cluster(cluster_id) ON DELETE CASCADE,
  first_seen         TIMESTAMPTZ NOT NULL,
  last_seen          TIMESTAMPTZ NOT NULL,
  link_strength      NUMERIC(10,4) NOT NULL DEFAULT 0,
  last_event_hash    TEXT,
  PRIMARY KEY (campaign_id, cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_campaign_infra_cluster_cluster ON campaign_infra_cluster(cluster_id);

-- Link explanations (why campaign uses this infra cluster)
CREATE TABLE IF NOT EXISTS campaign_infra_explanation (
  campaign_id        UUID NOT NULL,
  cluster_id         UUID NOT NULL,
  explanation_id     UUID NOT NULL REFERENCES explanation(explanation_id) ON DELETE CASCADE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (campaign_id, cluster_id, explanation_id),
  FOREIGN KEY (campaign_id, cluster_id)
    REFERENCES campaign_infra_cluster(campaign_id, cluster_id) ON DELETE CASCADE
);
