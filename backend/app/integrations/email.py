from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domains.foundation.models import OrganizationIntegrationCredential
from app.integrations.credential_crypto import CredentialCryptoError, decrypt_secret


class EmailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    use_ssl: bool

    @property
    def configured(self) -> bool:
        return bool(self.host.strip() and self.from_email.strip() and (not self.username.strip() or self.password))


def environment_smtp_config() -> SmtpConfig:
    settings = get_settings()
    return SmtpConfig(
        host=settings.email_smtp_host, port=settings.email_smtp_port,
        username=settings.email_smtp_username, password=settings.email_smtp_password,
        from_email=settings.email_smtp_from_email, from_name=settings.email_smtp_from_name,
        use_tls=settings.email_smtp_use_tls, use_ssl=settings.email_smtp_use_ssl,
    )


def smtp_config_for_organization(db: Session, organization_id: UUID) -> SmtpConfig:
    row = db.scalar(select(OrganizationIntegrationCredential).where(
        OrganizationIntegrationCredential.organization_id == organization_id,
        OrganizationIntegrationCredential.provider == "smtp",
    ))
    if row is None:
        return environment_smtp_config()
    values = dict(row.non_secret_config or {})
    password = ""
    if row.encrypted_secret:
        try:
            password = decrypt_secret(row.encrypted_secret, scope=f"{organization_id}:smtp")
        except CredentialCryptoError as exc:
            raise EmailDeliveryError(str(exc)) from exc
    return SmtpConfig(
        host=str(values.get("host") or ""), port=int(values.get("port") or 587),
        username=str(values.get("username") or ""), password=password,
        from_email=str(values.get("from_email") or ""), from_name=str(values.get("from_name") or ""),
        use_tls=bool(values.get("use_tls", True)), use_ssl=bool(values.get("use_ssl", False)),
    )


def smtp_configured(config: SmtpConfig | None = None) -> bool:
    return (config or environment_smtp_config()).configured


def _deliver(message: EmailMessage, config: SmtpConfig) -> None:
    if not config.configured:
        raise EmailDeliveryError("O envio de e-mail transacional ainda não está configurado.")
    try:
        if config.use_ssl:
            client: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=12)
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=12)
        with client:
            client.ehlo()
            if config.use_tls and not config.use_ssl:
                client.starttls()
                client.ehlo()
            if config.username.strip():
                client.login(config.username, config.password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Não foi possível entregar o e-mail pelo servidor SMTP configurado.") from exc


def send_email_message(
    *,
    recipient: str,
    subject: str,
    text_body: str,
    organization_name: str,
    attachments: list[dict[str, Any]] | None = None,
    config: SmtpConfig | None = None,
) -> None:
    config = config or environment_smtp_config()
    if not config.configured:
        raise EmailDeliveryError("O envio de e-mail transacional ainda não está configurado.")
    message = EmailMessage()
    message["Subject"] = subject.strip() or organization_name
    message["From"] = formataddr((config.from_name.strip() or organization_name, config.from_email.strip()))
    message["To"] = recipient
    message.set_content(text_body)
    html_body = "<br>".join(escape(text_body).splitlines())
    message.add_alternative(
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;color:#1d242b;line-height:1.55\">"
        f"<div style=\"max-width:680px;margin:auto\">{html_body}</div>"
        "</body></html>",
        subtype="html",
    )
    for attachment in attachments or []:
        content = attachment.get("content")
        filename = str(attachment.get("filename") or "documento.bin")
        content_type = str(attachment.get("content_type") or "application/octet-stream")
        if not isinstance(content, (bytes, bytearray)):
            continue
        maintype, _, subtype = content_type.partition("/")
        message.add_attachment(bytes(content), maintype=maintype or "application", subtype=subtype or "octet-stream", filename=filename)
    _deliver(message, config)


def send_portal_verification_email(
    *,
    recipient: str,
    code: str,
    organization_name: str,
    purpose: str,
    config: SmtpConfig | None = None,
) -> None:
    config = config or environment_smtp_config()
    if not config.configured:
        raise EmailDeliveryError("O envio de e-mail do portal ainda não está configurado.")

    first_access = purpose == "first_access"
    action = "criar sua senha" if first_access else "redefinir sua senha"
    subject = f"{organization_name} · {'Primeiro acesso' if first_access else 'Redefinição de senha'}"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.from_name.strip() or organization_name, config.from_email.strip()))
    message["To"] = recipient
    message.set_content(
        f"Olá!\n\nUse o código abaixo para {action} no Portal do Inquilino:\n\n{code}\n\n"
        f"O código expira em 10 minutos e pode ser utilizado apenas uma vez.\n"
        f"Se você não solicitou esta alteração, ignore esta mensagem.\n\n{organization_name}"
    )
    message.add_alternative(
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;color:#1d242b\">"
        f"<p>Olá!</p><p>Use o código abaixo para {escape(action)} no Portal do Inquilino:</p>"
        f"<p style=\"font-size:28px;font-weight:700;letter-spacing:6px\">{escape(code)}</p>"
        "<p>O código expira em <strong>10 minutos</strong> e pode ser utilizado apenas uma vez.</p>"
        "<p>Se você não solicitou esta alteração, ignore esta mensagem.</p>"
        f"<p>{escape(organization_name)}</p></body></html>",
        subtype="html",
    )
    _deliver(message, config)
