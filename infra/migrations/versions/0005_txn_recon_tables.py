"""Phase-3 tables: transaction sources/imports/rows + recon runs/items."""
from __future__ import annotations

from alembic import op

revision = "0005_txn_recon_tables"
down_revision = "0004_evaluation_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE txn_source_configs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            kind            TEXT NOT NULL,
            name            TEXT NOT NULL UNIQUE,
            active          BOOLEAN NOT NULL DEFAULT true,
            config          JSONB NOT NULL,
            credentials_enc TEXT,
            schedule_cron   TEXT,
            last_pulled_at  TIMESTAMPTZ,
            created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE txn_imports (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_config_id UUID REFERENCES txn_source_configs(id) ON DELETE SET NULL,
            kind             TEXT NOT NULL,
            trade_date       DATE NOT NULL,
            file_name        TEXT,
            gcs_uri          TEXT,
            status           TEXT NOT NULL DEFAULT 'pending',
            row_count        INTEGER NOT NULL DEFAULT 0,
            imported_count   INTEGER NOT NULL DEFAULT 0,
            skipped_count    INTEGER NOT NULL DEFAULT 0,
            errors           JSONB NOT NULL DEFAULT '[]',
            created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at     TIMESTAMPTZ
        );
        CREATE INDEX ix_txn_imports_trade_date ON txn_imports (trade_date);
        """
    )

    op.execute(
        """
        CREATE TABLE transactions (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            import_id      UUID NOT NULL REFERENCES txn_imports(id) ON DELETE CASCADE,
            ext_txn_id     TEXT,
            trade_date     DATE NOT NULL,
            ordered_at     TIMESTAMPTZ,
            executed_at    TIMESTAMPTZ,
            broker_code    TEXT,
            client_account TEXT,
            client_name    TEXT,
            stock_code     TEXT,
            stock_name     TEXT,
            side           TEXT NOT NULL,
            quantity       NUMERIC(18,2),
            price          NUMERIC(18,4),
            amount         NUMERIC(18,2),
            channel        TEXT,
            raw            JSONB NOT NULL DEFAULT '{}'
        );
        CREATE INDEX ix_transactions_trade_date ON transactions (trade_date);
        CREATE INDEX ix_transactions_broker_code_executed_at
            ON transactions (broker_code, executed_at);
        CREATE INDEX ix_transactions_stock_code_trade_date
            ON transactions (stock_code, trade_date);
        CREATE UNIQUE INDEX uq_transactions_ext_txn_id_trade_date
            ON transactions (ext_txn_id, trade_date) WHERE ext_txn_id IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE recon_runs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            trade_date      DATE NOT NULL,
            status          TEXT NOT NULL DEFAULT 'running',
            params_snapshot JSONB NOT NULL,
            stats           JSONB,
            error           TEXT,
            started_by      UUID REFERENCES users(id) ON DELETE SET NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ
        );
        CREATE INDEX ix_recon_runs_trade_date ON recon_runs (trade_date);
        """
    )

    op.execute(
        """
        CREATE TABLE recon_items (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id               UUID NOT NULL REFERENCES recon_runs(id) ON DELETE CASCADE,
            item_type            TEXT NOT NULL,
            severity             TEXT NOT NULL,
            transaction_id       UUID REFERENCES transactions(id) ON DELETE SET NULL,
            recording_id         UUID REFERENCES recordings(id) ON DELETE SET NULL,
            trade_instruction_id UUID REFERENCES trade_instructions(id) ON DELETE SET NULL,
            score                NUMERIC(6,4),
            score_breakdown      JSONB NOT NULL DEFAULT '{}',
            match_status         TEXT NOT NULL DEFAULT 'unmatched',
            review_note          TEXT,
            reviewed_by          UUID REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at          TIMESTAMPTZ
        );
        CREATE INDEX ix_recon_items_run_id_item_type ON recon_items (run_id, item_type);
        CREATE INDEX ix_recon_items_transaction_id ON recon_items (transaction_id);
        CREATE INDEX ix_recon_items_recording_id ON recon_items (recording_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recon_items;")
    op.execute("DROP TABLE IF EXISTS recon_runs;")
    op.execute("DROP TABLE IF EXISTS transactions;")
    op.execute("DROP TABLE IF EXISTS txn_imports;")
    op.execute("DROP TABLE IF EXISTS txn_source_configs;")
