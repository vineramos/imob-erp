from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from app.core.config import get_settings


class EmailDeliveryError(RuntimeError):
    pass


def smtp_configured() -> bool:
    return get_settings().email_smtp_configured


def send_portal_verification_email(
    *,
    recipient: str,
    code: str,
    organization_name: str,
    purpose: str,
) -> None:
    settings = get_settings()
    if not settings.email_smtp_configured:
        raise EmailDeliveryError("O envio de e-mail do portal ainda não está configurado.")

    first_access = purpose == "first_access"
    action = "criar sua senha" if first_access else "redefinir sua senha"
    subject = f"{organization_name} · {'Primeiro acesso' if first_access else 'Redefinição de senha'}"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(
        (settings.email_smtp_from_name.strip() or organization_name, settings.email_smtp_from_email.strip())
    )
    message["To"] = recipient
    message.set_content(
        f"Olá!\n\n"
        f"Use o código abaixo para {action} no Portal do Inquilino:\n\n"
        f"{code}\n\n"
        f"O código expira em 10 minutos e pode ser utilizado apenas uma vez.\n"
        f"Se você não solicitou esta alteração, ignore esta mensagem.\n\n"
        f"{organization_name}"
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

    try:
        if settings.email_smtp_use_ssl:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.email_smtp_host,
                settings.email_smtp_port,
                timeout=12,
            )
        else:
            client = smtplib.SMTP(
                settings.email_smtp_host,
                settings.email_smtp_port,
                timeout=12,
            )
        with client:
            client.ehlo()
            if settings.email_smtp_use_tls and not settings.email_smtp_use_ssl:
                client.starttls()
                client.ehlo()
            if settings.email_smtp_username.strip():
                client.login(settings.email_smtp_username, settings.email_smtp_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Não foi possível enviar o código de acesso por e-mail.") from exc
