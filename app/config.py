from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")
    app_title: str = Field(default="Majic Movie Selector", alias="APP_TITLE")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )

    tmdb_api_key: str | None = Field(default=None, alias="TMDB_API_KEY")

    plex_base_url: str = Field(default="http://localhost:32400", alias="PLEX_BASE_URL")
    plex_token: str | None = Field(default=None, alias="PLEX_TOKEN")

    radarr_base_url: str = Field(default="http://localhost:7878", alias="RADARR_BASE_URL")
    radarr_api_key: str | None = Field(default=None, alias="RADARR_API_KEY")

    usenet_base_url: str = Field(default="http://localhost:5076", alias="USENET_BASE_URL")
    usenet_api_key: str | None = Field(default=None, alias="USENET_API_KEY")

    source_timeout_seconds: float = 8.0

    data_dir: Path = Path("data")
    memory_db_path: Path = Path("data/memory.sqlite")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


settings = Settings()
