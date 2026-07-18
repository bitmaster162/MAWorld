-- Контур самоулучшения (docs/04). Отдельная миграция: включается на Фазе B.
CREATE TABLE IF NOT EXISTS improvement_proposal (
  proposal_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  target_type        TEXT NOT NULL CHECK (target_type IN ('PROMPT','SKILL','CODE','CONFIG')),
  target_ref         TEXT NOT NULL,
  risk_class         TEXT NOT NULL CHECK (risk_class IN ('LOW','MEDIUM','HIGH','FORBIDDEN')),
  hypothesis         TEXT NOT NULL,
  evidence_trace_ids TEXT[],
  diff_artifact_id   UUID,
  parent_version     TEXT,
  branch_id          TEXT,
  eval_dataset_id    TEXT NOT NULL,
  baseline_eval_id   TEXT,
  required_delta     REAL,
  status TEXT NOT NULL DEFAULT 'PROPOSED'
    CHECK (status IN ('PROPOSED','BUILT','EVALUATED','GATED','CANARY','PROMOTED','ROLLED_BACK','ARCHIVED')),
  human_approval_id  TEXT,
  rollback_ref       TEXT NOT NULL,      -- без пути отката строка не создаётся
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT no_forbidden CHECK (risk_class <> 'FORBIDDEN')  -- FORBIDDEN-цели не проходят даже INSERT
);
CREATE TABLE IF NOT EXISTS improvement_loop_state (
  singleton            BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
  improvement_loop_enabled BOOLEAN NOT NULL DEFAULT FALSE,   -- kill-switch контура, fail closed
  updated_by TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO improvement_loop_state (improvement_loop_enabled) VALUES (FALSE) ON CONFLICT DO NOTHING;
