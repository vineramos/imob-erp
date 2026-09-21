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
    # Chave opcional dedicada à criptografia de credenciais cadastradas pelo ERP.
    # Quando vazia, a DATABASE_URL (segredo exclusivo do servidor) é usada como
    # material de chave, mantendo dumps do banco incapazes de revelar as senhas.
    credentials_encryption_key: str = ""

    # Segredos de integrações entram somente por ambiente/Secret Manager.
    # Nunca são persistidos nas configurações operacionais do ERP.
    clicksign_access_token: str = ""
    clicksign_environment: str = "sandbox"
    clicksign_webhook_secret: str = ""

    # E-mail transacional da Central de Comunicações e do Portal. Senha SMTP
    # fica somente no ambiente/Secret Manager. Nome vazio usa o nome da organização.
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_smtp_from_email: str = ""
    email_smtp_from_name: str = ""
    email_smtp_use_tls: bool = True
    email_smtp_use_ssl: bool = False

    # WhatsApp Business Platform / Cloud API oficial da Meta. Token, App Secret
    # e verify token ficam somente no ambiente/Secret Manager.
    whatsapp_graph_version: str = "v26.0"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_waba_id: str = ""
    whatsapp_webhook_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_default_country_code: str = "55"

    # Banco Inter Empresas. As credenciais e o certificado mTLS ficam apenas
    # no ambiente/Secret Manager. O ERP persiste somente IDs e respostas
    # operacionais necessárias para rastrear cobranças e movimentações.
    inter_environment: str = "sandbox"
    inter_client_id: str = ""
    inter_client_secret: str = ""
    inter_cert_path: str = ""
    inter_key_path: str = ""
    inter_account_number: str = ""
    inter_webhook_secret: str = ""

    # Storage próprio para documentos finais/contratuais. Em Cloud Run, a
    # autenticação usa a service account do runtime; nenhuma chave JSON é
    # necessária nem permitida pela aplicação.
    document_storage_bucket: str = ""
    document_storage_prefix: str = "imob-erp"
    document_storage_migrate_on_start: bool = False

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

    @property
    def clicksign_base_url(self) -> str:
        if self.clicksign_environment.strip().lower() == "production":
            return "https://app.clicksign.com/api/v3"
        return "https://sandbox.clicksign.com/api/v3"

    @property
    def email_smtp_configured(self) -> bool:
        if not self.email_smtp_host.strip() or not self.email_smtp_from_email.strip():
            return False
        if self.email_smtp_username.strip() and not self.email_smtp_password:
            return False
        return True

    @property
    def whatsapp_configured(self) -> bool:
        return bool(self.whatsapp_access_token.strip() and self.whatsapp_phone_number_id.strip())

    @property
    def whatsapp_webhook_configured(self) -> bool:
        return bool(self.whatsapp_webhook_verify_token.strip() and self.whatsapp_app_secret.strip())

    @property
    def whatsapp_messages_url(self) -> str:
        version = self.whatsapp_graph_version.strip().lstrip("/") or "v26.0"
        return f"https://graph.facebook.com/{version}/{self.whatsapp_phone_number_id.strip()}/messages"

    @property
    def inter_base_url(self) -> str:
        if self.inter_environment.strip().lower() == "production":
            return "https://cdpj.partners.bancointer.com.br"
        return "https://cdpj-sandbox.partners.uatinter.co"

    @property
    def inter_configured(self) -> bool:
        return all((self.inter_client_id, self.inter_client_secret, self.inter_cert_path, self.inter_key_path))


@lru_cache
def get_settings() -> Settings:
    return Settings()
