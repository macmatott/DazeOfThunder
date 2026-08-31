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

    # Posted by the CI/CD pipeline's changelog job after a successful
    # auto-deploy, via /internal/post-changelog — see post_changelog in
    # discord_webhooks.py and .github/scripts/post_deploy_changelog.py.
    discord_webhook_changelog: str = ""

    # Posted the moment the YouTube channel is detected going live (see
    # app/services/discord_webhooks.py::check_and_notify_youtube_live).
    # A dedicated GitHub Actions cron hits /internal/check-youtube-live
    # every few minutes to trigger the check, since the Fly.io machine
    # auto-stops when idle and can't run its own background poll loop.
    discord_webhook_youtube_live: str = ""

    # Posted once a week ahead of the upcoming Thursday sim race (see
    # app/services/discord_webhooks.py::check_and_post_race_week_reminder),
    # via a GitHub Actions cron hitting /internal/check-race-week-reminder.
    discord_webhook_race_reminder: str = ""

    # The league's Discord role id, pinged (<@&id>) by the race-week
    # reminder post. Not a secret in the usual sense (anyone in the
    # server can see a role's id), but kept in settings rather than
    # hardcoded so it isn't tied to app code.
    discord_role_id_league: str = ""

    # Shared secret the cron workflows send as the X-Cron-Secret header
    # so the /internal/* routes can't be triggered by anyone else
    # hitting the public URL. Set via .env locally / `fly secrets set`
    # in production; never commit a real value.
    internal_cron_secret: str = ""

    environment: str = "development"
    log_level: str = "INFO"


settings = Settings()
