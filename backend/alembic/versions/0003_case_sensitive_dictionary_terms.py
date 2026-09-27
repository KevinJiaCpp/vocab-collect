"""Preserve case-distinct dictionary terms.

Revision ID: 0003_case_sensitive_dictionary_terms
Revises: 0002_dictionary_mwe_setting
"""

import sqlalchemy as sa
from alembic import op


revision = "0003_case_sensitive_dictionary_terms"
down_revision = "0002_dictionary_mwe_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("dictionary_terms")}
    if "search_term" in columns:
        return
    op.add_column("dictionary_terms", sa.Column("search_term", sa.String(240), nullable=False, server_default=""))
    op.execute("UPDATE dictionary_terms SET search_term = normalized_term, normalized_term = term")
    op.create_index("ix_dictionary_terms_search_term", "dictionary_terms", ["search_term"])


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("dictionary_terms")}
    if "search_term" not in columns:
        return
    op.execute("DELETE FROM dictionary_terms WHERE id NOT IN (SELECT MIN(id) FROM dictionary_terms GROUP BY search_term)")
    op.execute("UPDATE dictionary_terms SET normalized_term = search_term")
    op.drop_index("ix_dictionary_terms_search_term", table_name="dictionary_terms")
    op.drop_column("dictionary_terms", "search_term")
