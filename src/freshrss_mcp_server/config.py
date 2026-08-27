"""Configuration management for FreshRSS MCP Server."""

import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Path the Google Reader API is served under, stripped to derive the web UI root.
_API_PATH_SUFFIX = "/api/greader.php"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # FreshRSS API Configuration
    freshrss_api_url: str
    freshrss_username: str
    freshrss_api_password: str

    # Public URL of the FreshRSS web UI, used to build links back to articles.
    # Often differs from freshrss_api_url: with Docker Compose the API is reached
    # over an internal hostname that is not resolvable from the user's browser.
    # When unset, it is derived from freshrss_api_url (see freshrss_web_url).
    freshrss_base_url: str | None = None

    # Optional settings with defaults
    request_timeout: int = 30
    default_article_limit: int = 100

    # Dynamic fetch settings (optional "playwright" extra; disabled by default)
    enable_dynamic_fetch: bool = False
    browser_timeout: int = 30

    # MCP Server Configuration
    mcp_transport: Literal["stdio", "sse", "streamable-http"] = "sse"
    mcp_host: str = "::"  # Listen on all interfaces (IPv4 + IPv6)
    mcp_port: int = 8080

    @model_validator(mode="before")
    @classmethod
    def use_railway_port(cls, data: dict) -> dict:
        """Use Railway's PORT if MCP_PORT is not explicitly set."""
        # Railway injects PORT, we prefer MCP_PORT but fallback to PORT
        if "mcp_port" not in data and "MCP_PORT" not in os.environ:
            railway_port = os.environ.get("PORT")
            if railway_port:
                data["mcp_port"] = int(railway_port)
        return data

    # Logging Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # API Authentication (optional)
    # If set, requires Authorization: Bearer <api_key> header
    api_key: str | None = None

    @field_validator("freshrss_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        """Reject a base URL without a scheme, so typos fail at startup."""
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("FRESHRSS_BASE_URL must start with http:// or https://")
        return value

    @property
    def freshrss_web_url(self) -> str:
        """Root URL of the FreshRSS web UI, without a trailing slash.

        Falls back to deriving the root from freshrss_api_url when
        FRESHRSS_BASE_URL is not set. That is correct for the common
        single-host deployment, but not when the API is reached over a
        private network, which is why the override exists.
        """
        if self.freshrss_base_url:
            return self.freshrss_base_url.rstrip("/")

        api_url = self.freshrss_api_url.rstrip("/")
        if api_url.endswith(_API_PATH_SUFFIX):
            return api_url[: -len(_API_PATH_SUFFIX)]

        # Unrecognised API path: fall back to the bare origin.
        parts = urlsplit(api_url)
        return f"{parts.scheme}://{parts.netloc}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: Application settings loaded from environment.

    Raises:
        ValidationError: If required settings are missing.
    """
    # pydantic-settings loads required fields from environment variables
    return Settings()  # type: ignore[call-arg]


def clear_settings_cache() -> None:
    """Clear the settings cache. Useful for testing."""
    get_settings.cache_clear()
