"""Карточка выплаты для админ-реестра."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database.models import WithdrawalAdminStatus, WithdrawalRequest, WithdrawalStatus
from services.fps_banks import fps_bank_title

_API_STATUS_RU = {
    WithdrawalStatus.CREATED: "Создана в API",
    WithdrawalStatus.EXECUTED: "Исполнена",
    WithdrawalStatus.MANUALPAY: "Ручная оплата",
    WithdrawalStatus.FAILED: "Ошибка",
}

_ADMIN_STATUS_RU = {
    WithdrawalAdminStatus.PENDING: "Ожидает решения",
    WithdrawalAdminStatus.APPROVED: "Подтверждена админом",
    WithdrawalAdminStatus.REJECTED: "Отклонена админом",
}


def format_payout_datetime(dt: datetime | None, tz_name: str) -> str:
    if not dt:
        return "—"
    aware = dt.replace(tzinfo=timezone.utc)
    local = aware.astimezone(ZoneInfo(tz_name))
    return local.strftime("%d.%m.%Y %H:%M")


def parse_payout_ref(text: str | None) -> int | None:
    """#wd5, wd5, выплата 5."""
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower().replace(" ", "")
    m = re.search(r"(?:#|№)?wd(\d+)$", low)
    if m:
        return int(m.group(1))
    m = re.search(r"выплата(?:#|№)?(\d+)$", low)
    if m:
        return int(m.group(1))
    return None


def payout_row_dict(req: WithdrawalRequest, tz_name: str) -> dict:
    u = req.user
    un = f"@{u.username}" if (u and u.username) else "—"
    tg = u.telegram_id if u else "—"
    return {
        "id": req.id,
        "number": f"wd{req.id}",
        "username": un,
        "telegram_id": tg,
        "amount": float(req.amount or 0),
        "phone": req.fps_phone or "—",
        "bank": fps_bank_title(req.fps_bank_member_id or ""),
        "bank_id": req.fps_bank_member_id or "—",
        "status": req.status,
        "status_label": _API_STATUS_RU.get(req.status, req.status),
        "admin_status": req.admin_status,
        "admin_status_label": _ADMIN_STATUS_RU.get(req.admin_status, req.admin_status),
        "payment_id": req.external_payment_id or "—",
        "error": (req.error_message or "—").strip()[:500],
        "created_at": format_payout_datetime(req.created_at, tz_name),
        "admin_decided_at": format_payout_datetime(req.admin_decided_at, tz_name),
    }


def format_payout_card_html(req: WithdrawalRequest, tz_name: str) -> str:
    row = payout_row_dict(req, tz_name)
    body = (
        f"Номер: <b>·#wd{row['id']}</b>\n"
        f"Пользователь: <b>{row['username']}</b> (Telegram ID <code>{row['telegram_id']}</code>)\n"
        f"Сумма: <b>{row['amount']:.2f}</b> ₽\n"
        f"Телефон СБП: <code>{row['phone']}</code>\n"
        f"Банк: <b>{row['bank']}</b> (<code>{row['bank_id']}</code>)\n"
        f"Дата заявки: <b>{row['created_at']}</b> ({tz_name})\n"
        f"Статус API: <b>{row['status_label']}</b>\n"
        f"ID платежа API: <code>{row['payment_id']}</code>\n"
        f"Модерация: <b>{row['admin_status_label']}</b>\n"
        f"Решение админа: {row['admin_decided_at']}\n"
        f"Ошибка: {row['error']}"
    )
    return f"💳 <b>Выплата ·#wd{row['id']}</b>\n\n<blockquote>{body}</blockquote>"
