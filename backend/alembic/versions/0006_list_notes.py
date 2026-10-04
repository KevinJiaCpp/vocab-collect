"""Own notes through word lists and attach them to any number of list entries.

Revision ID: 0006_list_notes
Revises: 0005_example_sentence_cache
"""

import unicodedata

import sqlalchemy as sa
from alembic import op


revision = "0006_list_notes"
down_revision = "0005_example_sentence_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    schema = sa.inspect(connection)
    # 0001 creates current metadata on fresh installations.
    if not schema.has_table("list_notes"):
        op.create_table(
            "list_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("word_list_id", sa.Integer(), sa.ForeignKey("word_lists.id", ondelete="CASCADE"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_list_notes_word_list_id", "list_notes", ["word_list_id"])
    if not schema.has_table("note_entries"):
        op.create_table(
            "note_entries",
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("list_notes.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("entry_id", sa.Integer(), sa.ForeignKey("word_list_entries.id", ondelete="CASCADE"), primary_key=True),
        )
        op.create_index("idx_note_entries_entry", "note_entries", ["entry_id"])
    if not schema.has_table("notes"):
        return
    metadata = sa.MetaData()
    old_notes = sa.Table("notes", metadata, autoload_with=connection)
    lists = sa.Table("word_lists", metadata, autoload_with=connection)
    entries = sa.Table("word_list_entries", metadata, autoload_with=connection)
    notes = sa.Table("list_notes", metadata, autoload_with=connection)
    links = sa.Table("note_entries", metadata, autoload_with=connection)
    dictionary_terms = sa.Table("dictionary_terms", metadata, autoload_with=connection)
    recovery_lists: dict[int, int] = {}
    for old in connection.execute(sa.select(old_notes).order_by(old_notes.c.id)).mappings():
        memberships = connection.execute(sa.select(entries.c.id, entries.c.word_list_id).join(
            lists, lists.c.id == entries.c.word_list_id,
        ).where(lists.c.user_id == old["user_id"], entries.c.normalized_word == old["normalized_word"])).all()
        if not memberships:
            user_id = old["user_id"]
            if user_id not in recovery_lists:
                used_names = set(connection.scalars(sa.select(lists.c.name).where(lists.c.user_id == user_id)))
                name = "Imported notes"
                suffix = 2
                while name in used_names:
                    name = f"Imported notes ({suffix})"
                    suffix += 1
                recovery_lists[user_id] = connection.execute(lists.insert().values(
                    user_id=user_id, name=name, direction="w2m", is_active=False,
                    created_at=old["updated_at"], updated_at=old["updated_at"],
                )).inserted_primary_key[0]
            list_id = recovery_lists[user_id]
            position = connection.scalar(sa.select(sa.func.count()).select_from(entries).where(entries.c.word_list_id == list_id))
            display_key = " ".join(unicodedata.normalize("NFKC", old["display_word"]).split())
            has_definition = connection.scalar(sa.select(dictionary_terms.c.id).where(dictionary_terms.c.normalized_term == display_key)) is not None
            entry_id = connection.execute(entries.insert().values(
                word_list_id=list_id, word=old["display_word"], normalized_word=old["normalized_word"],
                position=position, has_definition=has_definition,
            )).inserted_primary_key[0]
            memberships = [(entry_id, list_id)]
        for entry_id, list_id in memberships:
            note_id = connection.execute(notes.insert().values(
                word_list_id=list_id, body=old["body"], updated_at=old["updated_at"],
            )).inserted_primary_key[0]
            connection.execute(links.insert().values(note_id=note_id, entry_id=entry_id))
    op.drop_table("notes")


def downgrade() -> None:
    connection = op.get_bind()
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("normalized_word", sa.String(240), nullable=False),
        sa.Column("display_word", sa.String(240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "normalized_word", name="uq_notes_user_word"),
    )
    op.create_index("ix_notes_user_id", "notes", ["user_id"])
    metadata = sa.MetaData()
    notes = sa.Table("list_notes", metadata, autoload_with=connection)
    lists = sa.Table("word_lists", metadata, autoload_with=connection)
    links = sa.Table("note_entries", metadata, autoload_with=connection)
    entries = sa.Table("word_list_entries", metadata, autoload_with=connection)
    legacy = sa.Table("notes", metadata, autoload_with=connection)
    rows = connection.execute(sa.select(
        notes.c.id, notes.c.body, notes.c.updated_at, lists.c.user_id, lists.c.name,
        entries.c.normalized_word, entries.c.word,
    ).join(lists, lists.c.id == notes.c.word_list_id).outerjoin(
        links, links.c.note_id == notes.c.id,
    ).outerjoin(entries, entries.c.id == links.c.entry_id).order_by(notes.c.id)).mappings()
    combined: dict[tuple[int, str], dict] = {}
    for row in rows:
        # The old model has one body per word. Preserve every body, including
        # unattached notes under a distinct recovery name when rolling back.
        normalized = row["normalized_word"] or f"unlinked-note-{row['id']}"
        key = (row["user_id"], normalized)
        value = combined.setdefault(key, {
            "user_id": row["user_id"], "normalized_word": normalized,
            "display_word": row["word"] or f"Note from {row['name']}",
            "body": [], "updated_at": row["updated_at"],
        })
        value["body"].append(f"[{row['name']}]\n{row['body']}")
        value["updated_at"] = max(value["updated_at"], row["updated_at"])
    for value in combined.values():
        value["body"] = "\n\n".join(value["body"])
        connection.execute(legacy.insert().values(**value))
    op.drop_table("note_entries")
    op.drop_table("list_notes")
