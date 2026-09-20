"""SMTP delivery helpers.

Kept separate from the bot runtime so both the scheduler and the API layer can
send mail without importing ``nonebot_bot`` (which would create a cycle).
"""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.db import connection
from app.repositories import meta_repo


def _smtp_send(settings, recipient: str, subject: str, body: str) -> None:
    config = _smtp_config(settings)
    if not config["host"] or not config["from_address"]:
        raise RuntimeError("SMTP_HOST 和 SMTP_FROM 未配置")
    message = EmailMessage()
    message["From"] = config["from_address"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    smtp_class = smtplib.SMTP_SSL if config["ssl"] else smtplib.SMTP
    with smtp_class(config["host"], config["port"], timeout=config["timeout"]) as server:
        server.ehlo()
        if config["starttls"] and not config["ssl"]:
            server.starttls()
            server.ehlo()
        if config["username"]:
            server.login(config["username"], config["password"])
        server.send_message(message)


def _smtp_config(settings) -> dict[str, object]:
    values = {
        "host": settings.smtp_host, "port": settings.smtp_port, "username": settings.smtp_username,
        "password": settings.smtp_password, "from_address": settings.smtp_from,
        "starttls": settings.smtp_starttls, "ssl": settings.smtp_ssl, "timeout": settings.smtp_timeout,
    }
    try:
        with connection() as conn:
            mapping = meta_repo.get_by_prefix(conn, "smtp_")
        for key, value in mapping.items():
            short = key.removeprefix("smtp_")
            if short in values:
                if short in {"port", "timeout"}:
                    values[short] = int(value)
                elif short in {"starttls", "ssl"}:
                    values[short] = value.lower() == "true"
                elif short == "from":
                    values["from_address"] = value
                else:
                    values[short] = value
    except Exception:
        pass
    return values


async def send_smtp_email(settings, recipient: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_smtp_send, settings, recipient, subject, body)
