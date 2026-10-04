from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


def migration_config(tmp_path, monkeypatch, name):
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    url = f"sqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    return config, create_engine(url)


def test_notes_migration_fresh_install_and_rollback_preserves_unlinked_bodies(tmp_path, monkeypatch):
    config, engine = migration_config(tmp_path, monkeypatch, "fresh.db")
    command.upgrade(config, "head")
    schema = inspect(engine)
    assert schema.has_table("list_notes") and schema.has_table("note_entries")
    assert not schema.has_table("notes")
    assert {column["name"] for column in schema.get_columns("list_notes")} == {"id", "word_list_id", "body", "updated_at"}
    assert schema.get_foreign_keys("list_notes")[0]["options"]["ondelete"] == "CASCADE"
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, username, username_key, password_hash, optimizer_status, created_at) VALUES (1, 'Reader', 'reader', 'test', 'idle', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO word_lists (id, user_id, name, direction, is_active, created_at, updated_at) VALUES (1, 1, 'First', 'w2m', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO word_list_entries (id, word_list_id, word, normalized_word, position, has_definition) VALUES (1, 1, 'Lucid', 'lucid', 0, 1)"))
        for note_id, body in ((1, "First body"), (2, "Second body"), (3, "Unlinked body")):
            connection.execute(text("INSERT INTO list_notes (id, word_list_id, body, updated_at) VALUES (:id, 1, :body, CURRENT_TIMESTAMP)"), {"id": note_id, "body": body})
        connection.execute(text("INSERT INTO note_entries (note_id, entry_id) VALUES (1, 1), (2, 1)"))
    command.downgrade(config, "0005_example_sentence_cache")
    assert inspect(engine).has_table("notes") and not inspect(engine).has_table("list_notes")
    with engine.connect() as connection:
        recovered = connection.execute(text("SELECT normalized_word, body FROM notes ORDER BY normalized_word")).all()
        assert len(recovered) == 2
        assert "First body" in recovered[0].body and "Second body" in recovered[0].body
        assert "Unlinked body" in recovered[1].body
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM list_notes")) == 2
        assert "Unlinked body" in "\n".join(connection.scalars(text("SELECT body FROM list_notes")))
    engine.dispose()


def test_legacy_notes_migrate_to_all_owned_lists_and_collision_free_recovery(tmp_path, monkeypatch):
    config, engine = migration_config(tmp_path, monkeypatch, "legacy.db")
    command.upgrade(config, "0005_example_sentence_cache")
    with engine.begin() as connection:
        # 0001 uses current metadata. Recreate the actual pre-0006 note schema.
        connection.execute(text("DROP TABLE note_entries"))
        connection.execute(text("DROP TABLE list_notes"))
        connection.execute(text("CREATE TABLE notes (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, normalized_word VARCHAR(240) NOT NULL, display_word VARCHAR(240) NOT NULL, body TEXT NOT NULL, updated_at DATETIME NOT NULL, CONSTRAINT uq_notes_user_word UNIQUE (user_id, normalized_word))"))
        connection.execute(text("INSERT INTO users (id, username, username_key, password_hash, optimizer_status, created_at) VALUES (1, 'Reader', 'reader', 'test', 'idle', CURRENT_TIMESTAMP), (2, 'Other', 'other', 'test', 'idle', CURRENT_TIMESTAMP)"))
        for list_id, owner, name, active in ((1, 1, "Active", True), (2, 1, "Paused", False), (3, 1, "Imported notes", True), (4, 1, "Imported notes (2)", False), (5, 2, "Other", True)):
            connection.execute(text("INSERT INTO word_lists (id, user_id, name, direction, is_active, created_at, updated_at) VALUES (:id, :owner, :name, 'w2m', :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"id": list_id, "owner": owner, "name": name, "active": active})
        connection.execute(text("INSERT INTO word_list_entries (id, word_list_id, word, normalized_word, position, has_definition) VALUES (1, 1, 'Lucid', 'lucid', 0, 1), (2, 2, 'LUCID', 'lucid', 0, 1), (3, 5, 'Lucid', 'lucid', 0, 1)"))
        connection.execute(text("INSERT INTO dictionary_terms (term, normalized_term, search_term) VALUES ('Resilient', 'Resilient', 'resilient'), ('Lost word', 'Lost word', 'lost word')"))
        for note_id, owner, normalized, display, body in ((1, 1, "lucid", "Lucid", " Original\nbody "), (2, 1, "resilient", "Resilient", "Lost membership"), (3, 2, "lucid", "Lucid", "Private other body"), (4, 1, "lost word", "Lost Word", "Another lost body")):
            connection.execute(text("INSERT INTO notes (id, user_id, normalized_word, display_word, body, updated_at) VALUES (:id, :owner, :word, :display, :body, '2020-01-02 03:04:05')"), {"id": note_id, "owner": owner, "word": normalized, "display": display, "body": body})
    command.upgrade(config, "head")
    assert not inspect(engine).has_table("notes")
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT n.body, n.updated_at, l.user_id, l.name, l.is_active, e.word, e.normalized_word, e.position, e.has_definition FROM list_notes n JOIN word_lists l ON l.id=n.word_list_id JOIN note_entries a ON a.note_id=n.id JOIN word_list_entries e ON e.id=a.entry_id ORDER BY n.id")).mappings().all()
        assert len(rows) == 5
        originals = [row for row in rows if row["body"] == " Original\nbody "]
        assert {row["name"] for row in originals} == {"Active", "Paused"}
        assert all(row["user_id"] == 1 for row in originals)
        assert all(row["updated_at"] == "2020-01-02 03:04:05.000000" for row in rows)
        recovery = [row for row in rows if row["name"] == "Imported notes (3)"]
        assert [(row["word"], row["position"]) for row in recovery] == [("Resilient", 0), ("Lost Word", 1)]
        assert [row["has_definition"] for row in recovery] == [1, 0]
        assert all(row["is_active"] == 0 and row["user_id"] == 1 for row in recovery)
        private = [row for row in rows if row["user_id"] == 2]
        assert len(private) == 1 and private[0]["body"] == "Private other body"
        assert connection.scalar(text("SELECT COUNT(*) FROM word_lists")) == 6
    engine.dispose()
