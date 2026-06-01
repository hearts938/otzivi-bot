from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import SupportTicket, User
from handlers.formatting import blockquote, support_ticket_admin_text
from handlers.keyboards import admin_support_item_kb
from repo import save_support_admin_message


async def send_support_ticket_to_admin(
    bot: Bot,
    session: AsyncSession,
    admin_telegram_id: int,
    ticket: SupportTicket,
    user: User,
    *,
    queue_hint: int | None = None,
) -> Message | None:
    text = support_ticket_admin_text(ticket, user)
    if queue_hint is not None:
        text += (
            f"\n\n{blockquote(f'Открытых обращений: {queue_hint}. '
                             f'Ответьте реплаем на это сообщение или нажмите «Ответить» на клавиатуре.')}"
        )
    kb = admin_support_item_kb(ticket.id)
    try:
        if ticket.photo_file_id:
            msg = await bot.send_photo(
                admin_telegram_id,
                ticket.photo_file_id,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            msg = await bot.send_message(
                admin_telegram_id,
                text,
                reply_markup=kb,
                parse_mode="HTML",
            )
    except (TelegramForbiddenError, TelegramBadRequest):
        return None
    await save_support_admin_message(session, ticket.id, admin_telegram_id, msg.message_id)
    return msg
