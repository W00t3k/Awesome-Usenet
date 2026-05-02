from datetime import datetime
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LimitsConfig(BaseSettings):
    """Centralized configuration for all data limits and year ranges."""

    # Year ranges (1900 = beginning of cinema, None = no limit)
    min_year: int = Field(default=1900, alias="LIMITS_MIN_YEAR")
    max_year: int | None = Field(default=None, alias="LIMITS_MAX_YEAR")  # None = current year + 2

    # API result limits (large values for "unlimited" behavior)
    recommendations_max: int = Field(default=100000, alias="LIMITS_RECOMMENDATIONS_MAX")
    usenet_max: int = Field(default=500, alias="LIMITS_USENET_MAX")
    browse_max: int = Field(default=100000, alias="LIMITS_BROWSE_MAX")
    seen_max: int = Field(default=100000, alias="LIMITS_SEEN_MAX")
    feedback_max: int = Field(default=100000, alias="LIMITS_FEEDBACK_MAX")

    # Data source pagination limits
    tmdb_max_pages: int = Field(default=500, alias="LIMITS_TMDB_MAX_PAGES")
    rogerebert_max_pages: int = Field(default=200, alias="LIMITS_ROGEREBERT_MAX_PAGES")
    usenet_batch_size: int = Field(default=500, alias="LIMITS_USENET_BATCH_SIZE")

    # Pagination defaults
    default_page_size: int = Field(default=50, alias="LIMITS_DEFAULT_PAGE_SIZE")
    max_page_size: int = Field(default=10000, alias="LIMITS_MAX_PAGE_SIZE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def get_max_year(self) -> int:
        """Returns max_year or current year + 2 if None."""
        if self.max_year is not None:
            return self.max_year
        return datetime.now().year + 2


class Settings(BaseSettings):
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8443, alias="APP_PORT")
    app_title: str = Field(default="Majic Movie", alias="APP_TITLE")

    tmdb_api_key: str | None = Field(default=None, alias="TMDB_API_KEY")
    rottentomatoes_list_url: str | None = Field(
        default="https://www.rottentomatoes.com/browse/movies_at_home/sort:popular",
        alias="ROTTENTOMATOES_LIST_URL",
    )
    releases_url: str | None = Field(
        default="https://www.releases.com/calendar/movie",
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

    # SABnzbd direct download (for grabbing specific releases)
    sabnzbd_url: str | None = Field(default=None, alias="SABNZBD_URL")
    sabnzbd_api_key: str | None = Field(default=None, alias="SABNZBD_API_KEY")

    # Ollama (local, optional)
    ollama_base_url: str | None = Field(default=None, alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.2:1b", alias="OLLAMA_MODEL")

    # Groq Cloud (fast inference, free tier)
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")

    # Qdrant Cloud (RAG vector database)
    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    source_timeout_seconds: float = 8.0

    data_dir: Path = Path("data")
    memory_db_path: Path = Path("data/memory.sqlite")

    # Authentication
    jwt_secret: str | None = Field(default=None, alias="JWT_SECRET")

    # Google OAuth
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://0.0.0.0:8443/api/auth/google/callback",
        alias="GOOGLE_REDIRECT_URI",
    )

    # Background jobs (Redis/RQ)
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Scheduled sync cron expressions
    oscars_sync_cron: str = Field(default="0 3 * * 0", alias="OSCARS_SYNC_CRON")  # Weekly Sunday 3am
    criterion_sync_cron: str = Field(default="0 4 1 * *", alias="CRITERION_SYNC_CRON")  # Monthly 1st 4am
    usenet_poll_interval_minutes: int = Field(default=30, alias="USENET_POLL_INTERVAL_MINUTES")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


settings = Settings()
limits = LimitsConfig()
