"""Add dictionary multiword-expression preference.

Revision ID: 0002_dictionary_mwe_setting
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op


revision = "0002_dictionary_mwe_setting"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("study_settings")}
    if "exclude_multiword_expressions" not in columns:
        op.add_column(
            "study_settings",
            sa.Column("exclude_multiword_expressions", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("study_settings")}
    if "exclude_multiword_expressions" in columns:
        with op.batch_alter_table("study_settings") as batch_op:
            batch_op.drop_column("exclude_multiword_expressions")
