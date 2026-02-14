from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")
    app_title: str = Field(default="Majic Movie Selector", alias="APP_TITLE")

    tmdb_api_key: str | None = Field(default=None, alias="TMDB_API_KEY")
    rottentomatoes_list_url: str | None = Field(
        default="https://www.rottentomatoes.com/browse/movies_at_home/sort:popular",
        alias="ROTTENTOMATOES_LIST_URL",
    )
    releases_url: str | None = Field(
        default="https://www.releases.com/calendar/movies/upcoming",
        alias="RELEASES_URL",
    )
    rogerebert_reviews_url: str | None = Field(
        default="https://www.rogerebert.com/reviews",
        alias="ROGEREBERT_REVIEWS_URL",
    )

    plex_base_url: str = Field(default="http://localhost:32400", alias="PLEX_BASE_URL")
    plex_token: str | None = Field(default=None, alias="PLEX_TOKEN")

    radarr_base_url: str = Field(default="http://localhost:7878", alias="RADARR_BASE_URL")
    radarr_api_key: str | None = Field(default=None, alias="RADARR_API_KEY")

    nzbgeek_rss_url: str | None = Field(
        default=(
            "https://api.nzbgeek.info/rss?t=search&cat=2000&apikey={API_KEY}"
        ),
        alias="NZBGEEK_RSS_URL",
    )
    nzbgeek_api_key: str | None = Field(default=None, alias="NZBGEEK_API_KEY")

    drunkenslug_base_url: str = Field(
        default="https://drunkenslug.com/api",
        alias="DRUNKENSLUG_BASE_URL",
    )
    drunkenslug_api_key: str | None = Field(default=None, alias="DRUNKENSLUG_API_KEY")

    usenet_base_url: str = Field(default="http://localhost:5076", alias="USENET_BASE_URL")
    usenet_api_key: str | None = Field(default=None, alias="USENET_API_KEY")

    source_timeout_seconds: float = 8.0

    data_dir: Path = Path("data")
    memory_db_path: Path = Path("data/memory.sqlite")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


settings = Settings()
