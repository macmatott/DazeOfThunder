"""
Central configuration for the Discord bot, loaded from environment variables.

The bot is a thin client: it reads from Supabase (via the supabase-py client,
respecting row-level security as an authenticated service role for read
access to standings/results) and posts formatted messages to Discord. It
does not hold scoring logic, CSV parsing, or draft logic — that all lives in
the website/backend against the same Supabase project.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Discord
    discord_bot_token: str = ""
    discord_guild_id: int | None = None
    discord_admin_role_id: int | None = None

    # Supabase — same project the website uses. Use the service_role key
    # here (server-side only, never in the bot's Discord-facing output)
    # so the bot can read tables without needing per-user auth.
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # App
    environment: str = "development"
    log_level: str = "INFO"


settings = Settings()
