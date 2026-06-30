"""Phase-2 evaluation tables.

- eval_criteria / extraction_fields: admin-edited config that drives both
  the evaluator prompt and the Gemini response schema
- evaluations (+ criteria/fields snapshots) / evaluation_results / trade_instructions
- llm_usage: daily token rollup for the budget guard
"""
from __future__ import annotations

from alembic import op

revision = "0004_evaluation_tables"
down_revision = "0003_pipeline_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE eval_criteria (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key         TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            description TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'compliance',
            score_type  TEXT NOT NULL DEFAULT 'pass_fail',
            severity    TEXT NOT NULL DEFAULT 'warning',
            weight      DOUBLE PRECISION NOT NULL DEFAULT 1,
            active      BOOLEAN NOT NULL DEFAULT true,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE extraction_fields (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key          TEXT NOT NULL UNIQUE,
            label        TEXT NOT NULL,
            description  TEXT,
            field_type   TEXT NOT NULL DEFAULT 'string',
            enum_options JSONB,
            scope        TEXT NOT NULL DEFAULT 'call',
            is_system    BOOLEAN NOT NULL DEFAULT false,
            active       BOOLEAN NOT NULL DEFAULT true,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE evaluations (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            recording_id          UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            run_seq               INTEGER NOT NULL,
            status                TEXT NOT NULL DEFAULT 'pending',
            llm_model             TEXT,
            criteria_snapshot     JSONB NOT NULL,
            fields_snapshot       JSONB NOT NULL,
            summary               TEXT,
            overall_score         NUMERIC(5,2),
            risk_flags            JSONB NOT NULL DEFAULT '[]',
            extracted_call_fields JSONB NOT NULL DEFAULT '{}',
            review_status         TEXT NOT NULL DEFAULT 'unreviewed',
            review_note           TEXT,
            reviewed_by           UUID REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at           TIMESTAMPTZ,
            error                 TEXT,
            input_tokens          INTEGER,
            output_tokens         INTEGER,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at          TIMESTAMPTZ,
            CONSTRAINT uq_evaluations_recording_id_run_seq UNIQUE (recording_id, run_seq)
        );
        CREATE INDEX ix_evaluations_recording_id ON evaluations (recording_id);
        """
    )

    op.execute(
        """
        CREATE TABLE evaluation_results (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evaluation_id   UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
            criterion_key   TEXT NOT NULL,
            criterion_name  TEXT NOT NULL,
            score           NUMERIC(5,2),
            passed          BOOLEAN,
            rationale       TEXT,
            evidence        JSONB NOT NULL DEFAULT '[]',
            severity        TEXT,
            override_score  NUMERIC(5,2),
            override_passed BOOLEAN,
            override_note   TEXT,
            overridden_by   UUID REFERENCES users(id) ON DELETE SET NULL,
            overridden_at   TIMESTAMPTZ
        );
        CREATE INDEX ix_evaluation_results_evaluation_id ON evaluation_results (evaluation_id);
        """
    )

    op.execute(
        """
        CREATE TABLE trade_instructions (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            evaluation_id      UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
            recording_id       UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            seq                INTEGER NOT NULL DEFAULT 0,
            stock_code         TEXT,
            stock_name_raw     TEXT,
            side               TEXT NOT NULL DEFAULT 'unknown',
            quantity           NUMERIC(18,2),
            price              NUMERIC(18,4),
            price_type         TEXT NOT NULL DEFAULT 'unknown',
            client_name_raw    TEXT,
            client_account_raw TEXT,
            time_in_call_ms    INTEGER,
            confidence         DOUBLE PRECISION,
            extra_fields       JSONB NOT NULL DEFAULT '{}',
            evidence_quote     TEXT
        );
        CREATE INDEX ix_trade_instructions_evaluation_id ON trade_instructions (evaluation_id);
        CREATE INDEX ix_trade_instructions_recording_id ON trade_instructions (recording_id);
        CREATE INDEX ix_trade_instructions_stock_code ON trade_instructions (stock_code);
        """
    )

    op.execute(
        """
        CREATE TABLE llm_usage (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            day           DATE NOT NULL,
            callsite      TEXT NOT NULL,
            model         TEXT NOT NULL,
            input_tokens  BIGINT NOT NULL DEFAULT 0,
            output_tokens BIGINT NOT NULL DEFAULT 0,
            requests      INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_llm_usage_day_callsite_model UNIQUE (day, callsite, model)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS llm_usage;")
    op.execute("DROP TABLE IF EXISTS trade_instructions;")
    op.execute("DROP TABLE IF EXISTS evaluation_results;")
    op.execute("DROP TABLE IF EXISTS evaluations;")
    op.execute("DROP TABLE IF EXISTS extraction_fields;")
    op.execute("DROP TABLE IF EXISTS eval_criteria;")
