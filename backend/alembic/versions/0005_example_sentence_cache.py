"""Cache generated examples per account and dictionary sense.

Revision ID: 0005_example_sentence_cache
Revises: 0004_llm_settings
"""

import sqlalchemy as sa
from alembic import op


revision = "0005_example_sentence_cache"
down_revision = "0004_llm_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration creates current metadata on fresh installations.
    if not sa.inspect(op.get_bind()).has_table("example_sentence_cache"):
        op.create_table(
            "example_sentence_cache",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("word", sa.String(240), primary_key=True),
            sa.Column("sense_key", sa.String(64), primary_key=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("example_sentence_cache")
