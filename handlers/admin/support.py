from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import SupportTicketStatus
from handlers.admin.common import is_admin
from handlers.support_states import SupportAdminFSM
from handlers.formatting import blockquote
from handlers.keyboards import (
    A_SUPPORT,
    admin_back_home_kb,
    admin_support_item_kb,
    parse_support_action,
)
from repo import (
    count_open_support_tickets,
    get_oldest_open_support_ticket,
    get_support_ticket,
    get_support_ticket_by_admin_reply,
    set_support_ticket_status,
)
from services.support_delivery import send_support_ticket_to_admin

router = Router(name="admin_support")


async def _push_ticket_to_admin(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        open_cnt = await count_open_support_tickets(session)
        ticket = await get_oldest_open_support_ticket(session)
    if not ticket or not ticket.user:
        await message.answer(
            f"📩 <b>Поддержка</b>\n\n{blockquote('Нет открытых обращений.')}",
            parse_mode="HTML",
            reply_markup=admin_back_home_kb(),
        )
        return
    async with session_factory() as session:
        sent = await send_support_ticket_to_admin(
            message.bot,
            session,
            message.from_user.id,
            ticket,
            ticket.user,
            queue_hint=open_cnt,
        )
    if not sent:
        await message.answer("Не удалось отправить обращение.", reply_markup=admin_back_home_kb())


@router.message(F.text == A_SUPPORT)
async def msg_support_inbox(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await _push_ticket_to_admin(message, session_factory, settings)


@router.message(F.text.func(lambda t: parse_support_action(t) is not None))
async def msg_support_action(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    parsed = parse_support_action(message.text or "")
    if not parsed:
        return
    action, ticket_id = parsed
    if action == "reject":
        await _reject_ticket(message, session_factory, ticket_id, state)
        return
    async with session_factory() as session:
        ticket = await get_support_ticket(session, ticket_id, with_user=True)
    if not ticket:
        await message.answer("Обращение не найдено.", reply_markup=admin_back_home_kb())
        return
    if ticket.status != SupportTicketStatus.OPEN:
        await message.answer(
            f"Обращение ·#sup{ticket_id} уже обработано.",
            reply_markup=admin_back_home_kb(),
        )
        return
    await state.set_state(SupportAdminFSM.waiting_reply)
    await state.update_data(support_ticket_id=ticket_id)
    await message.answer(
        f"✉️ Ответ на ·#sup{ticket_id}\n\n"
        f"{blockquote('Напишите ответ реплаем на сообщение с обращением выше '
                       '(кнопка «Ответить» в Telegram). Можно также просто отправить '
                       'текст или фото следующим сообщением.')}",
        parse_mode="HTML",
        reply_markup=admin_support_item_kb(ticket_id),
    )


async def _deliver_support_answer(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    ticket_id: int,
) -> bool:
    async with session_factory() as session:
        ticket = await get_support_ticket(session, ticket_id, with_user=True)
        if not ticket or ticket.status != SupportTicketStatus.OPEN:
            return False
        user = ticket.user
        if not user:
            return False
        reply_body = (message.text or message.caption or "").strip()
        if not reply_body and not message.photo:
            await message.answer("Пустой ответ. Напишите текст или отправьте фото.")
            return False
        try:
            if message.photo:
                await message.bot.send_photo(
                    user.telegram_id,
                    message.photo[-1].file_id,
                    caption=reply_body or None,
                )
            else:
                await message.bot.send_message(user.telegram_id, reply_body)
        except (TelegramForbiddenError, TelegramBadRequest):
            await message.answer("Не удалось доставить ответ пользователю.")
            return False
        await set_support_ticket_status(session, ticket.id, SupportTicketStatus.ANSWERED)
    return True


@router.message(SupportAdminFSM.waiting_reply)
async def msg_support_admin_reply(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    if not ticket_id:
        await state.clear()
        return

    resolved_id = int(ticket_id)
    if message.reply_to_message:
        async with session_factory() as session:
            by_reply = await get_support_ticket_by_admin_reply(
                session, message.from_user.id, message.reply_to_message.message_id
            )
        if by_reply and by_reply.status == SupportTicketStatus.OPEN:
            resolved_id = by_reply.id

    if message.text and parse_support_action(message.text):
        return

    ok = await _deliver_support_answer(message, session_factory, resolved_id)
    if not ok:
        await message.answer(
            "Не удалось отправить ответ. Проверьте, что обращение ещё открыто.",
            reply_markup=admin_support_item_kb(int(ticket_id)),
        )
        return
    await state.clear()
    await message.answer(
        f"✅ Ответ отправлен пользователю (·#sup{resolved_id}).",
        reply_markup=admin_back_home_kb(),
    )


async def _reject_ticket(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    ticket_id: int,
    state: FSMContext,
) -> None:
    await state.clear()
    async with session_factory() as session:
        ticket = await get_support_ticket(session, ticket_id, with_user=True)
        if not ticket:
            await message.answer("Обращение не найдено.", reply_markup=admin_back_home_kb())
            return
        if ticket.status != SupportTicketStatus.OPEN:
            await message.answer(
                f"Обращение ·#sup{ticket_id} уже обработано.",
                reply_markup=admin_back_home_kb(),
            )
            return
        await set_support_ticket_status(session, ticket.id, SupportTicketStatus.REJECTED)
        user = ticket.user
    await message.answer(
        f"❌ Обращение ·#sup{ticket_id} отклонено.",
        reply_markup=admin_back_home_kb(),
    )
    if user:
        try:
            await message.bot.send_message(
                user.telegram_id,
                "Ваше обращение в поддержку закрыто без ответа.",
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
