from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOCAB_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = REPO_ROOT / "data"
    database_url: str = ""
    secure_cookies: bool = False
    allowed_origins: str = (
        "http://127.0.0.1:8000,http://localhost:8000,"
        "http://127.0.0.1:5173,http://localhost:5173"
    )
    session_days: int = 30
    lexicon: str = "oewn:2025+"

    def model_post_init(self, __context: object) -> None:
        self.data_dir = Path(self.data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = REPO_ROOT / self.data_dir
        self.data_dir = self.data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'vocab_collect.db').as_posix()}"

    @property
    def origin_set(self) -> set[str]:
        return {value.strip().rstrip("/") for value in self.allowed_origins.split(",") if value.strip()}

    @property
    def wn_dir(self) -> Path:
        path = self.data_dir / "wn"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cmudict_path(self) -> Path:
        return self.data_dir / "cmudict" / "cmudict.dict"


settings = Settings()
