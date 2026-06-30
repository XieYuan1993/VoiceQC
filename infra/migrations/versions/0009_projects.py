"""Flat projects — scope recordings + evaluation config per project.

Adds a `projects` table and a project_id FK to the core ingest + config
tables (upload_batches, recordings, eval_criteria, extraction_fields,
industry_terms), and reworks app_settings to a (project_id, key) primary key.

Existing data, if present, is housed in a default "Quam Securities" project so
nothing is lost; fresh installs get their default project from the seed. The
securities-module tables (brokers, transactions, recon_*) are scoped in a
later migration, when reconciliation becomes an optional per-project module.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_projects"
down_revision = "0008_recording_client_identity"
branch_labels = None
depends_on = None

# Deterministic id for the data-backfill project (only created when upgrading
# a DB that already has data).
DEFAULT_PID = "00000000-0000-0000-0000-0000000000d1"
QUAM_CONTEXT = (
    "Inbound client calls to a Hong Kong securities brokerage. Licensed brokers "
    "(account executives) take orders to buy and sell Hong Kong-listed shares for "
    "clients. Calls are mostly in Cantonese, mixing English stock names and "
    "numbers. Judge regulatory compliance (SFC conduct) and service quality."
)

# project_id added + NOT NULL + indexed on all of these.
SCOPED_TABLES = [
    "upload_batches",
    "recordings",
    "eval_criteria",
    "extraction_fields",
    "industry_terms",
]


def upgrade() -> None:
    # --- projects table ----------------------------------------------------
    op.execute(
        """
        CREATE TABLE projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            modules JSONB NOT NULL DEFAULT '{}'::jsonb,
            eval_prompt_context TEXT,
            branding JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_default BOOLEAN NOT NULL DEFAULT false,
            active BOOLEAN NOT NULL DEFAULT true,
            archived_at TIMESTAMPTZ,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_projects_is_default ON projects (is_default) WHERE is_default;"
    )

    # --- nullable project_id on core + config tables -----------------------
    for tbl in [*SCOPED_TABLES, "app_settings"]:
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN project_id UUID;")
        op.execute(
            f"ALTER TABLE {tbl} ADD CONSTRAINT fk_{tbl}_project_id_projects "
            f"FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;"
        )

    # --- house existing data in a default project --------------------------
    bind = op.get_bind()
    has_data = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM app_settings "
            "UNION ALL SELECT 1 FROM eval_criteria "
            "UNION ALL SELECT 1 FROM upload_batches)"
        )
    ).scalar()
    if has_data:
        bind.execute(
            sa.text(
                "INSERT INTO projects (id, slug, name, is_default, modules, eval_prompt_context) "
                "VALUES (:pid, 'quam', 'Quam Securities', true, "
                '\'{"trade_reconciliation": true}\'::jsonb, :ctx)'
            ),
            {"pid": DEFAULT_PID, "ctx": QUAM_CONTEXT},
        )
        for tbl in [*SCOPED_TABLES, "app_settings"]:
            bind.execute(
                sa.text(f"UPDATE {tbl} SET project_id = :pid WHERE project_id IS NULL"),
                {"pid": DEFAULT_PID},
            )

    # --- enforce NOT NULL + index ------------------------------------------
    for tbl in SCOPED_TABLES:
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN project_id SET NOT NULL;")
        op.execute(f"CREATE INDEX ix_{tbl}_project_id ON {tbl} (project_id);")

    # --- app_settings: (project_id, key) primary key -----------------------
    op.execute("ALTER TABLE app_settings ALTER COLUMN project_id SET NOT NULL;")
    op.execute("ALTER TABLE app_settings DROP CONSTRAINT app_settings_pkey;")
    op.execute(
        "ALTER TABLE app_settings ADD CONSTRAINT app_settings_pkey PRIMARY KEY (project_id, key);"
    )

    # --- per-project unique keys (were globally unique) --------------------
    op.execute("ALTER TABLE eval_criteria DROP CONSTRAINT eval_criteria_key_key;")
    op.execute(
        "ALTER TABLE eval_criteria ADD CONSTRAINT uq_eval_criteria_project_id_key "
        "UNIQUE (project_id, key);"
    )
    op.execute("ALTER TABLE extraction_fields DROP CONSTRAINT extraction_fields_key_key;")
    op.execute(
        "ALTER TABLE extraction_fields ADD CONSTRAINT uq_extraction_fields_project_id_key "
        "UNIQUE (project_id, key);"
    )
    op.execute("ALTER TABLE industry_terms DROP CONSTRAINT industry_terms_canonical_key;")
    op.execute(
        "ALTER TABLE industry_terms ADD CONSTRAINT uq_industry_terms_project_id_canonical "
        "UNIQUE (project_id, canonical);"
    )


def downgrade() -> None:
    # Restore global unique keys (assumes a single project's worth of keys).
    op.execute("ALTER TABLE industry_terms DROP CONSTRAINT uq_industry_terms_project_id_canonical;")
    op.execute("ALTER TABLE industry_terms ADD CONSTRAINT industry_terms_canonical_key UNIQUE (canonical);")
    op.execute("ALTER TABLE extraction_fields DROP CONSTRAINT uq_extraction_fields_project_id_key;")
    op.execute("ALTER TABLE extraction_fields ADD CONSTRAINT extraction_fields_key_key UNIQUE (key);")
    op.execute("ALTER TABLE eval_criteria DROP CONSTRAINT uq_eval_criteria_project_id_key;")
    op.execute("ALTER TABLE eval_criteria ADD CONSTRAINT eval_criteria_key_key UNIQUE (key);")

    op.execute("ALTER TABLE app_settings DROP CONSTRAINT app_settings_pkey;")
    op.execute("ALTER TABLE app_settings ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);")

    for tbl in [*SCOPED_TABLES, "app_settings"]:
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN project_id;")  # drops FK + index

    op.execute("DROP TABLE projects;")
