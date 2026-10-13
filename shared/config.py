from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder values from .env.example — never acceptable in production.
_EXAMPLE_VALUES = frozenset({"change_me_in_production", "your_discord_bot_token_here"})


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

    storage_bucket_wip: str = "wip"
    storage_bucket_receipts: str = "receipts"

    environment: str = "development"
    api_base_url: str = "http://localhost:8000"

    sentry_dsn: str = ""

    # Optional: exchangerate.host key. Without it quotes are shown in PHP only.
    exchange_rate_access_key: str = ""

    db_pool_size: int = 20
    db_max_overflow: int = 50
    db_echo: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def require(self, *names: str) -> None:
        """Fail fast when a setting the calling process cannot run without is unset.

        Every setting has an empty default because the API, bot and workers share
        this class but need different subsets; each entry point names what it needs.
        """
        missing = [
            name.upper()
            for name in names
            if not getattr(self, name)
            or (self.is_production and getattr(self, name) in _EXAMPLE_VALUES)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required settings: {', '.join(missing)}. "
                "Set them in the environment or in .env"
            )


settings = Settings()