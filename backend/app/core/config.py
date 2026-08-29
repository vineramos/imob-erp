from functools import lru_cache
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Imob ERP Imobiliario"
    app_env: str = "development"
    database_url: str = ""
    neon_auth_url: str = ""
    neon_auth_jwks_url: str = ""
    bootstrap_admin_email: str = ""
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_neon_auth_jwks_url(self) -> str:
        if self.neon_auth_jwks_url:
            return self.neon_auth_jwks_url
        if self.neon_auth_url:
            return f"{self.neon_auth_url.rstrip('/')}/.well-known/jwks.json"
        return ""

    @property
    def effective_neon_auth_issuer(self) -> str:
        if not self.neon_auth_url:
            return ""
        parsed = urlparse(self.neon_auth_url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
