-- Explanation objects (first-class, immutable-ish)
CREATE TABLE IF NOT EXISTS explanation (
  explanation_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  explanation_type   TEXT NOT NULL,
  score              NUMERIC(10,4) NOT NULL DEFAULT 0,
  details            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_explanation_type ON explanation(explanation_type);
CREATE INDEX IF NOT EXISTS idx_explanation_created ON explanation(created_at);

-- Evidence refs anchoring explanation to facts
CREATE TABLE IF NOT EXISTS explanation_evidence (
  explanation_id     UUID NOT NULL REFERENCES explanation(explanation_id) ON DELETE CASCADE,
  event_hash         TEXT NOT NULL,
  source_id          TEXT,
  occurred_at        TIMESTAMPTZ,
  PRIMARY KEY (explanation_id, event_hash)
);

CREATE INDEX IF NOT EXISTS idx_expl_evidence_event_hash ON explanation_evidence(event_hash);
