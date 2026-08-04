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

    environment: str = "development"
    log_level: str = "INFO"


settings = Settings()
