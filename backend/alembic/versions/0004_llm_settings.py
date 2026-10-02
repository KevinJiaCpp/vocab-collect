"""Add per-user LLM configuration.

Revision ID: 0004_llm_settings
Revises: 0003_case_sensitive_dictionary_terms
"""

import sqlalchemy as sa
from alembic import op


revision = "0004_llm_settings"
down_revision = "0003_case_sensitive_dictionary_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration creates current metadata on fresh installations.
    if not sa.inspect(op.get_bind()).has_table("llm_settings"):
        op.create_table(
            "llm_settings",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("base_url", sa.String(2048), nullable=False),
            sa.Column("model", sa.String(200), nullable=False),
            sa.Column("api_key", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("llm_settings")
