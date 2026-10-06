"""convert tag-list columns from json to jsonb

PostgreSQL only offers containment (``@>``) and key-existence (``?|``) on jsonb.
These columns are *queried* (scheme state filters, knowledge-document tag filters,
semantic-search filters, farmer crop preferences), so leaving them as json meant
filters either errored (`operator does not exist: json ~~ text`) or silently
matched nothing. Write-only JSON blobs (audit snapshots, metrics, AI payloads)
are deliberately left as json.

A GIN index is added for the two columns that are filtered on every search.

Revision ID: 8b3c5d1e7f42
Revises: 7c1a4f0be5d2
Create Date: 2026-10-06 00:05:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8b3c5d1e7f42"
down_revision: Union[str, None] = "7c1a4f0be5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONVERTED: tuple[tuple[str, str], ...] = (
    ("schemes", "state_codes"),
    ("schemes", "crop_codes"),
    ("knowledge_documents", "crop_codes"),
    ("knowledge_documents", "state_codes"),
    ("knowledge_documents", "topics"),
    ("farmer_profiles", "primary_crops"),
    ("farmer_profiles", "interests"),
    ("crops_catalog", "disease_model_labels"),
)

GIN_INDEXES: tuple[tuple[str, str], ...] = (
    ("knowledge_documents", "crop_codes"),
    ("knowledge_documents", "state_codes"),
    ("schemes", "state_codes"),
)


def upgrade() -> None:
    for table, column in CONVERTED:
        op.alter_column(
            table,
            column,
            type_=postgresql.JSONB(astext_type=None),
            existing_type=postgresql.JSON(astext_type=None),
            existing_nullable=False,
            postgresql_using=f"{column}::jsonb",
        )
    for table, column in GIN_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_{column}_gin "
            f"ON {table} USING gin ({column})"
        )


def downgrade() -> None:
    for table, column in GIN_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_{column}_gin")
    for table, column in CONVERTED:
        op.alter_column(
            table,
            column,
            type_=postgresql.JSON(astext_type=None),
            existing_type=postgresql.JSONB(astext_type=None),
            existing_nullable=False,
            postgresql_using=f"{column}::json",
        )
