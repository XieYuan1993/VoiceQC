"""Phase-1 pipeline tables: batches, recordings, transcripts, terms, STT usage.

- upload_batches / recordings: the ingest state machine
  (uploaded -> converting -> transcribing [-> evaluating, Phase 2] -> completed | failed)
- transcripts (+ trigram GIN on full_text — Postgres FTS tokenizes Chinese
  poorly) / transcript_segments (channel-tagged, ms offsets)
- industry_terms: STT adaptation + LLM glossary + recon alias source
- stt_usage: daily audio-seconds rollup for the budget guard
"""
from __future__ import annotations

from alembic import op

revision = "0003_pipeline_tables"
down_revision = "0002_admin_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE batch_status AS ENUM
            ('open', 'processing', 'completed', 'completed_with_errors', 'failed');
        CREATE TYPE recording_status AS ENUM
            ('uploaded', 'converting', 'transcribing', 'evaluating', 'completed', 'failed');
        """
    )

    op.execute(
        """
        CREATE TABLE upload_batches (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name         TEXT,
            trade_date   DATE NOT NULL,
            status       batch_status NOT NULL DEFAULT 'open',
            total_files  INTEGER NOT NULL DEFAULT 0,
            created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            finalized_at TIMESTAMPTZ
        );
        """
    )

    op.execute(
        """
        CREATE TABLE recordings (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id           UUID NOT NULL REFERENCES upload_batches(id) ON DELETE CASCADE,
            original_filename  TEXT NOT NULL,
            sha256             TEXT NOT NULL,
            size_bytes         BIGINT NOT NULL,
            gcs_uri_raw        TEXT NOT NULL,
            gcs_uri_broker     TEXT,
            gcs_uri_customer   TEXT,
            gcs_uri_mono       TEXT,
            duration_seconds   NUMERIC(10,2),
            sample_rate        INTEGER,
            channels           INTEGER,
            format             TEXT,
            call_started_at    TIMESTAMPTZ,
            broker_ext         TEXT,
            caller_number      TEXT,
            direction          TEXT NOT NULL DEFAULT 'unknown',
            language_mode      TEXT,
            status             recording_status NOT NULL DEFAULT 'uploaded',
            failed_stage       TEXT,
            error              TEXT,
            attempts           INTEGER NOT NULL DEFAULT 0,
            stt_operation_name TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_recordings_batch_id_sha256 UNIQUE (batch_id, sha256)
        );
        CREATE INDEX ix_recordings_batch_id ON recordings (batch_id);
        CREATE INDEX ix_recordings_status ON recordings (status);
        CREATE INDEX ix_recordings_call_started_at ON recordings (call_started_at);
        CREATE INDEX ix_recordings_broker_ext_call_started_at
            ON recordings (broker_ext, call_started_at);
        """
    )

    op.execute(
        """
        CREATE TABLE transcripts (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            recording_id      UUID NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
            stt_model         TEXT NOT NULL,
            language_detected TEXT,
            full_text         TEXT NOT NULL,
            billed_seconds    NUMERIC(10,2),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_transcripts_full_text_trgm
            ON transcripts USING gin (full_text gin_trgm_ops);
        """
    )

    op.execute(
        """
        CREATE TABLE transcript_segments (
            id            BIGSERIAL PRIMARY KEY,
            transcript_id UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
            channel_role  TEXT NOT NULL,
            start_ms      INTEGER NOT NULL,
            end_ms        INTEGER NOT NULL,
            text          TEXT NOT NULL,
            language      TEXT,
            confidence    DOUBLE PRECISION
        );
        CREATE INDEX ix_transcript_segments_transcript_id_start_ms
            ON transcript_segments (transcript_id, start_ms);
        """
    )

    op.execute(
        """
        CREATE TABLE industry_terms (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category   TEXT NOT NULL,
            canonical  TEXT NOT NULL UNIQUE,
            stock_code TEXT,
            aliases    JSONB NOT NULL DEFAULT '[]',
            boost      DOUBLE PRECISION,
            active     BOOLEAN NOT NULL DEFAULT true,
            notes      TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_industry_terms_stock_code ON industry_terms (stock_code);
        """
    )

    op.execute(
        """
        CREATE TABLE stt_usage (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            day           DATE NOT NULL,
            provider      TEXT NOT NULL,
            model         TEXT NOT NULL,
            audio_seconds BIGINT NOT NULL DEFAULT 0,
            requests      INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_stt_usage_day_provider_model UNIQUE (day, provider, model)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stt_usage;")
    op.execute("DROP TABLE IF EXISTS industry_terms;")
    op.execute("DROP TABLE IF EXISTS transcript_segments;")
    op.execute("DROP TABLE IF EXISTS transcripts;")
    op.execute("DROP TABLE IF EXISTS recordings;")
    op.execute("DROP TABLE IF EXISTS upload_batches;")
    op.execute("DROP TYPE IF EXISTS recording_status;")
    op.execute("DROP TYPE IF EXISTS batch_status;")
