"""add user_consents

Per-purpose, versioned consent records (`app/users/models.UserConsent`).

Why a new table rather than columns on `farmer_profiles`: consent has to be
auditable (who decided what, when, from which client, against which policy
version) and purposes are independent — allowing product analytics must not
imply allowing model training on a farmer's photos. Dataset-building tooling
queries this table as an allow-list.

Both enum columns are stored as validated VARCHAR, matching the convention used
by the initial revision (`native_enum=False`), so no PostgreSQL enum types are
created and downgrades stay simple.

Revision ID: 7c1a4f0be5d2
Revises: 40d0fb1079db
Create Date: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c1a4f0be5d2"
down_revision = "40d0fb1079db"
branch_labels = None
depends_on = None

CONSENT_KINDS = (
    "analytics",
    "model_training",
    "research",
    "personalisation",
    "marketing",
    "location",
)
CONSENT_SOURCES = ("mobile_app", "web", "admin_console", "support", "seed", "import")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_consents" in inspector.get_table_names():
        return

    op.create_table(
        "user_consents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*CONSENT_KINDS, name="consent_kind", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(*CONSENT_SOURCES, name="consent_source", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("app_version", sa.String(length=24), nullable=True),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_consents")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_consents_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id", "kind", "policy_version", name="uq_user_consents_user_kind_version"
        ),
    )
    op.create_index(op.f("ix_user_consents_user_id"), "user_consents", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_consents_kind"), "user_consents", ["kind"], unique=False)
    op.create_index(
        "ix_user_consents_user_kind", "user_consents", ["user_id", "kind"], unique=False
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_consents" not in inspector.get_table_names():
        return
    op.drop_index("ix_user_consents_user_kind", table_name="user_consents")
    op.drop_index(op.f("ix_user_consents_kind"), table_name="user_consents")
    op.drop_index(op.f("ix_user_consents_user_id"), table_name="user_consents")
    op.drop_table("user_consents")
