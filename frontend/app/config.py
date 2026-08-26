"""
Frontend app configuration. The website reads Supabase with the anon key
by default (respecting RLS) for public/member-facing pages. Admin-only
operations (CSV upload, draft management, corrections) will use the
service_role key through dedicated admin routes once auth/roles are wired
up — never expose service_role to anything rendered in a template.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    f1_data_api_base_url: str = "https://api.jolpi.ca/ergast/f1"

    # YouTube Data API v3 key — powers the "are we live" nav indicator.
    # Free-tier Google Cloud credential, not a Supabase key. Optional: the
    # indicator just reports "offline" if this is unset. Set via .env
    # locally / `fly secrets set` in production; never commit a real value.
    youtube_api_key: str = ""

    # Signs the session cookie (Starlette SessionMiddleware) — a random
    # value, not a Supabase key. Set via .env locally / `fly secrets set`
    # in production; never commit a real value.
    secret_key: str = ""

    # Discord Incoming Webhook URLs — one per standings channel. Posted
    # to after an admin imports F1 results or uploads an iRacing CSV
    # (see app/services/discord_webhooks.py). Optional: posting is
    # silently skipped for any channel whose URL isn't set (e.g. local
    # dev). Set via .env locally / `fly secrets set` in production;
    # never commit a real value — anyone with the URL can post to that
    # channel.
    discord_webhook_drivers: str = ""
    discord_webhook_fantasy: str = ""
    discord_webhook_constructors: str = ""
    discord_webhook_overall: str = ""

    # Posted manually (not by any app request handler) after a commit is
    # pushed and deployed to prod — see post_changelog in
    # discord_webhooks.py. There's no CI pipeline here; deploys only
    # happen when explicitly requested, so this stays a deliberate step
    # in that same conversation rather than something triggered
    # automatically off of every git push.
    discord_webhook_changelog: str = ""

    environment: str = "development"
    log_level: str = "INFO"


settings = Settings()
