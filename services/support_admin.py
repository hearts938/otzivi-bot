"""Ответы на обращения в поддержку (бот и веб-админка)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import SupportTicketStatus
from repo import get_support_ticket, set_support_ticket_status


async def deliver_support_reply(
    bot: Bot,
    session: AsyncSession,
    ticket_id: int,
    *,
    text: str,
    photo_bytes: bytes | None = None,
    photo_filename: str = "photo.jpg",
) -> tuple[bool, str | None]:
    ticket = await get_support_ticket(session, ticket_id, with_user=True)
    if not ticket or ticket.status != SupportTicketStatus.OPEN:
        return False, "Обращение не найдено или уже обработано."
    user = ticket.user
    if not user:
        return False, "Пользователь не найден."
    body = (text or "").strip()
    if not body and not photo_bytes:
        return False, "Нужен текст ответа или фото."
    try:
        if photo_bytes:
            await bot.send_photo(
                user.telegram_id,
                BufferedInputFile(photo_bytes, filename=photo_filename),
                caption=body or None,
            )
        else:
            await bot.send_message(user.telegram_id, body)
    except (TelegramForbiddenError, TelegramBadRequest):
        return False, "Не удалось доставить ответ пользователю."
    await set_support_ticket_status(session, ticket.id, SupportTicketStatus.ANSWERED)
    return True, None


async def reject_support_ticket(
    bot: Bot,
    session: AsyncSession,
    ticket_id: int,
) -> tuple[bool, str | None]:
    ticket = await get_support_ticket(session, ticket_id, with_user=True)
    if not ticket:
        return False, "Обращение не найдено."
    if ticket.status != SupportTicketStatus.OPEN:
        return False, "Обращение уже обработано."
    await set_support_ticket_status(session, ticket.id, SupportTicketStatus.REJECTED)
    user = ticket.user
    if user:
        try:
            await bot.send_message(
                user.telegram_id,
                "Ваше обращение в поддержку закрыто без ответа.",
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
    return True, None
