from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    discord_token: str = ""
    bot_secret: str = ""

    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    supabase_url: str = ""
    supabase_service_key: str = ""

    storage_bucket_portfolio: str = "portfolio"
    storage_bucket_wip: str = "wip"
    storage_bucket_receipts: str = "receipts"

    environment: str = "development"
    api_base_url: str = "http://localhost:8007"

    email_verify_ttl: int = 86400

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()