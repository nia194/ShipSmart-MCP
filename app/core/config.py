"""
Application configuration for ShipSmart-MCP.
Loaded from environment variables via pydantic-settings; .env for local dev.
Production values are set in the Render dashboard.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    app_name: str = "shipsmart-mcp"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_allowed_origins: str = "http://localhost:5173,http://localhost:8000,http://localhost:8080"

    # ── Auth ─────────────────────────────────────────────────────────────────
    # Optional shared secret enforced on /tools/* when set.
    # Empty = auth disabled (local dev only).
    mcp_api_key: str = ""

    # ── Shipping Providers ───────────────────────────────────────────────────
    shipping_provider: str = "mock"  # "mock", "ups", "fedex", "dhl", "usps"

    # ── UPS ──────────────────────────────────────────────────────────────────
    ups_client_id: str = ""
    ups_client_secret: str = ""
    ups_account_number: str = ""
    ups_base_url: str = "https://onlinetools.ups.com"

    # ── FedEx ────────────────────────────────────────────────────────────────
    fedex_client_id: str = ""
    fedex_client_secret: str = ""
    fedex_account_number: str = ""
    fedex_base_url: str = "https://apis.fedex.com"

    # ── DHL ──────────────────────────────────────────────────────────────────
    dhl_api_key: str = ""
    dhl_api_secret: str = ""
    dhl_account_number: str = ""
    dhl_base_url: str = "https://express.api.dhl.com"

    # ── USPS ─────────────────────────────────────────────────────────────────
    usps_client_id: str = ""
    usps_client_secret: str = ""
    usps_base_url: str = "https://api.usps.com"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
