"""Пароль, сессии и коды подтверждения веб-админки."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from database.models import WebAdminEmailCode, WebAdminSession
from repo import get_setting, set_setting
from services.web_admin_email import send_admin_code_email

PASSWORD_HASH_KEY = "web_admin_password_hash"
OTP_PURPOSE_PASSWORD = "password_change"
OTP_TTL_MINUTES = 15
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), iters
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def client_ip_from_headers(*, forwarded_for: str | None, client_host: str | None) -> str:
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:64] or "unknown"
    if client_host:
        return client_host[:64]
    return "unknown"


async def ensure_password_initialized(session: AsyncSession, settings: Settings) -> None:
    stored = await get_setting(session, PASSWORD_HASH_KEY, "")
    if stored:
        return
    bootstrap = settings.web_admin_password
    if not bootstrap:
        return
    await set_setting(session, PASSWORD_HASH_KEY, hash_password(bootstrap))


async def verify_admin_password(
    session: AsyncSession, settings: Settings, password: str
) -> bool:
    await ensure_password_initialized(session, settings)
    stored = await get_setting(session, PASSWORD_HASH_KEY, "")
    if stored:
        return verify_password(password, stored)
    if settings.web_admin_password:
        return password == settings.web_admin_password
    return False


async def admin_password_is_configured(
    session: AsyncSession, settings: Settings
) -> bool:
    await ensure_password_initialized(session, settings)
    stored = await get_setting(session, PASSWORD_HASH_KEY, "")
    return bool(stored or settings.web_admin_password)


async def set_admin_password(session: AsyncSession, new_password: str) -> None:
    await set_setting(session, PASSWORD_HASH_KEY, hash_password(new_password))


async def create_web_admin_session(
    session: AsyncSession,
    *,
    ip_address: str,
    user_agent: str | None,
) -> WebAdminSession:
    now = datetime.utcnow()
    row = WebAdminSession(
        id=str(uuid4()),
        ip_address=ip_address[:64],
        user_agent=(user_agent or "")[:512] or None,
        created_at=now,
        last_seen_at=now,
    )
    session.add(row)
    await session.commit()
    return row


async def get_web_admin_session(
    session: AsyncSession, session_id: str
) -> WebAdminSession | None:
    row = await session.get(WebAdminSession, session_id)
    if not row or row.revoked_at:
        return None
    return row


async def touch_web_admin_session(session: AsyncSession, session_id: str) -> None:
    await session.execute(
        update(WebAdminSession)
        .where(
            WebAdminSession.id == session_id,
            WebAdminSession.revoked_at.is_(None),
        )
        .values(last_seen_at=datetime.utcnow())
    )


async def revoke_web_admin_session(session: AsyncSession, session_id: str) -> bool:
    row = await session.get(WebAdminSession, session_id)
    if not row or row.revoked_at:
        return False
    row.revoked_at = datetime.utcnow()
    await session.commit()
    return True


async def list_active_web_admin_sessions(
    session: AsyncSession,
) -> list[WebAdminSession]:
    r = await session.execute(
        select(WebAdminSession)
        .where(WebAdminSession.revoked_at.is_(None))
        .order_by(WebAdminSession.created_at.asc())
    )
    return list(r.scalars().all())


async def _invalidate_pending_codes(session: AsyncSession, purpose: str) -> None:
    now = datetime.utcnow()
    r = await session.execute(
        select(WebAdminEmailCode).where(
            WebAdminEmailCode.purpose == purpose,
            WebAdminEmailCode.used_at.is_(None),
            WebAdminEmailCode.expires_at > now,
        )
    )
    for row in r.scalars().all():
        row.used_at = now


async def issue_password_change_code(
    session: AsyncSession, settings: Settings
) -> None:
    if not settings.web_admin_email:
        raise RuntimeError("WEB_ADMIN_EMAIL не задан в .env")
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST не задан в .env")
    await _invalidate_pending_codes(session, OTP_PURPOSE_PASSWORD)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.utcnow()
    session.add(
        WebAdminEmailCode(
            code_hash=_hash_otp(code),
            purpose=OTP_PURPOSE_PASSWORD,
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
            created_at=now,
        )
    )
    await session.commit()
    await send_admin_code_email(settings, code=code)


async def verify_and_consume_password_code(
    session: AsyncSession, code: str
) -> bool:
    raw = (code or "").strip()
    if not raw.isdigit() or len(raw) != 6:
        return False
    now = datetime.utcnow()
    code_hash = _hash_otp(raw)
    r = await session.execute(
        select(WebAdminEmailCode)
        .where(
            WebAdminEmailCode.purpose == OTP_PURPOSE_PASSWORD,
            WebAdminEmailCode.code_hash == code_hash,
            WebAdminEmailCode.used_at.is_(None),
            WebAdminEmailCode.expires_at > now,
        )
        .order_by(WebAdminEmailCode.id.desc())
        .limit(1)
    )
    row = r.scalar_one_or_none()
    if not row:
        return False
    row.used_at = now
    await session.commit()
    return True


def format_session_row(row: WebAdminSession, tz_name: str) -> dict:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)

    def _fmt(dt: datetime | None) -> str:
        if not dt:
            return "—"
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")

    ua = (row.user_agent or "—").strip()
    if len(ua) > 80:
        ua = ua[:77] + "…"
    return {
        "id": row.id,
        "ip": row.ip_address,
        "user_agent": ua,
        "created_at": _fmt(row.created_at),
        "last_seen_at": _fmt(row.last_seen_at),
    }
