from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


def test_llm_migration_fresh_and_existing_database(tmp_path, monkeypatch):
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", database_url)
    command.upgrade(config, "0004_llm_settings")
    engine = create_engine(database_url)
    assert inspect(engine).has_table("llm_settings")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, username, username_key, password_hash, optimizer_status, created_at) VALUES (1, 'Reader', 'reader', 'test', 'idle', CURRENT_TIMESTAMP)"))
        # Reproduce an existing database from before this feature.
        connection.execute(text("DROP TABLE llm_settings"))
    command.stamp(config, "0003_case_sensitive_dictionary_terms")
    command.upgrade(config, "0004_llm_settings")
    schema = inspect(engine)
    assert {column["name"] for column in schema.get_columns("llm_settings")} == {"user_id", "base_url", "model", "api_key"}
    foreign_key = schema.get_foreign_keys("llm_settings")[0]
    assert foreign_key["referred_table"] == "users"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT username FROM users WHERE id = 1")) == "Reader"
    command.downgrade(config, "0003_case_sensitive_dictionary_terms")
    assert not inspect(engine).has_table("llm_settings")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT username FROM users WHERE id = 1")) == "Reader"
    engine.dispose()


def test_example_cache_migration_fresh_existing_and_rollback(tmp_path, monkeypatch):
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    database_url = f"sqlite:///{(tmp_path / 'examples.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", database_url)
    command.upgrade(config, "0005_example_sentence_cache")
    engine = create_engine(database_url)
    assert inspect(engine).has_table("example_sentence_cache")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, username, username_key, password_hash, optimizer_status, created_at) VALUES (1, 'Reader', 'reader', 'test', 'idle', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO llm_settings (user_id, base_url, model) VALUES (1, 'http://localhost:11434/v1', 'local')"))
        connection.execute(text("DROP TABLE example_sentence_cache"))
    command.stamp(config, "0004_llm_settings")
    command.upgrade(config, "0005_example_sentence_cache")
    schema = inspect(engine)
    assert schema.get_pk_constraint("example_sentence_cache")["constrained_columns"] == ["user_id", "word", "sense_key"]
    assert schema.get_foreign_keys("example_sentence_cache")[0]["options"]["ondelete"] == "CASCADE"
    command.downgrade(config, "0004_llm_settings")
    assert not inspect(engine).has_table("example_sentence_cache")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT username FROM users WHERE id = 1")) == "Reader"
        assert connection.scalar(text("SELECT model FROM llm_settings WHERE user_id = 1")) == "local"
    engine.dispose()
