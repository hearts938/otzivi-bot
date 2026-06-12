"""Отправка писем веб-админки (коды смены пароля)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from config import Settings

logger = logging.getLogger(__name__)


def _send_smtp_sync(settings: Settings, *, subject: str, body: str) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST не задан в .env")
    if not settings.web_admin_email:
        raise RuntimeError("WEB_ADMIN_EMAIL не задан в .env")
    from_addr = settings.smtp_from or settings.smtp_user
    if not from_addr:
        raise RuntimeError("SMTP_FROM или SMTP_USER не задан в .env")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = settings.web_admin_email
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_port == 587:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(from_addr, [settings.web_admin_email], msg.as_string())


async def send_admin_code_email(settings: Settings, *, code: str) -> None:
    body = (
        f"Код для смены пароля веб-админки: {code}\n\n"
        f"Код действует 15 минут. Если вы не запрашивали смену пароля — проигнорируйте письмо."
    )
    try:
        await asyncio.to_thread(
            _send_smtp_sync,
            settings,
            subject="Код смены пароля — админ-панель",
            body=body,
        )
    except Exception:
        logger.exception("Не удалось отправить код на %s", settings.web_admin_email)
        raise
