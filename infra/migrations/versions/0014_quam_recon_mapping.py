"""Preserve Quam order quantity and broker name during transaction import."""

from __future__ import annotations

from alembic import op

revision = "0014_quam_recon_mapping"
down_revision = "0013_recording_broker_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        UPDATE txn_source_configs
        SET config = jsonb_set(
            jsonb_set(
                jsonb_set(config, '{encoding}', '"gb18030"'::jsonb, true),
                '{column_mapping,order_quantity}',
                to_jsonb(U&'\59D4\8A17\6578\91CF'::text),
                true
            ),
            '{column_mapping,broker_name}',
            to_jsonb(U&'\59D4\8A17\4EBA'::text),
            true
        )
        WHERE name = 'Quam Client History Order Report';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE txn_source_configs
        SET config = jsonb_set(
            (config #- '{column_mapping,order_quantity}') #- '{column_mapping,broker_name}',
            '{encoding}',
            '"utf-8-sig"'::jsonb,
            true
        )
        WHERE name = 'Quam Client History Order Report';
        """
    )
