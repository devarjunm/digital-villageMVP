"""add is_demo index and users avatar fk

Two changes that the initial revision could not express:

  * `product_events.is_demo` — the model mixes in `DemoFlagMixin` (indexed), but the
    index was missing; analytics dashboards filter on this column.
  * `users.avatar_media_id` — the foreign key to `media_assets` was declared with
    `use_alter=True` to break the users ⇄ media_assets creation cycle, and the first
    revision therefore did not emit it. It is added here, after both tables exist.

Revision ID: 40d0fb1079db
Revises: e1d0628ce86d
Create Date: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "40d0fb1079db"
down_revision = "e1d0628ce86d"
branch_labels = None
depends_on = None

FK_NAME = "fk_users_avatar_media_id_media_assets"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_indexes = {index["name"] for index in inspector.get_indexes("product_events")}
    if "ix_product_events_is_demo" not in existing_indexes:
        op.create_index("ix_product_events_is_demo", "product_events", ["is_demo"], unique=False)

    existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("users")}
    if FK_NAME not in existing_fks:
        op.create_foreign_key(
            FK_NAME,
            "users",
            "media_assets",
            ["avatar_media_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("users")}
    if FK_NAME in existing_fks:
        op.drop_constraint(FK_NAME, "users", type_="foreignkey")

    existing_indexes = {index["name"] for index in inspector.get_indexes("product_events")}
    if "ix_product_events_is_demo" in existing_indexes:
        op.drop_index("ix_product_events_is_demo", table_name="product_events")
