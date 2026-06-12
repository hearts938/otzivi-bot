from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import Settings
from database.models import WithdrawalAdminStatus
from handlers.admin.common import is_admin
from handlers.formatting import blockquote
from handlers.keyboards import (
    A_WITHDRAWALS,
    admin_back_home_kb,
    admin_withdraw_item_kb,
    parse_withdraw_action,
)
from repo import list_pending_withdrawals, set_withdrawal_admin_decision
from services.fps_banks import fps_bank_title

router = Router(name="admin_withdrawals")


def _withdraw_card_text(req) -> str:
    u = req.user
    un = f"@{u.username}" if (u and u.username) else "—"
    tg = u.telegram_id if u else "—"
    pid = req.external_payment_id or "—"
    err = (req.error_message or "—").strip()
    info = (
        f"Сумма: {req.amount:.2f} ₽\n"
        f"Пользователь: {un} (ID {tg})\n"
        f"Телефон СБП: {req.fps_phone or '—'}\n"
        f"Банк СБП: {fps_bank_title(req.fps_bank_member_id or '')}\n"
        f"Статус API: {req.status}\n"
        f"ID платежа API: {pid}\n"
        f"Ошибка API: {err}"
    )
    return (
        f"💸 <b>Заявка на вывод ·#wd{req.id}</b>\n\n"
        f"{blockquote(info)}"
    )


@router.message(F.text == A_WITHDRAWALS)
async def msg_withdrawals_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        rows = await list_pending_withdrawals(session, limit=30)
    if not rows:
        await message.answer(
            f"💸 <b>Заявки на вывод</b>\n\n{blockquote('Нет неподтвержденных заявок.')}",
            parse_mode="HTML",
            reply_markup=admin_back_home_kb(),
        )
        return
    await message.answer(
        f"💸 <b>Заявки на вывод</b>\n\n"
        f"{blockquote(f'Неподтвержденных: {len(rows)}. Выберите действие под каждой заявкой.')}",
        parse_mode="HTML",
        reply_markup=admin_back_home_kb(),
    )
    for req in rows:
        await message.answer(
            _withdraw_card_text(req),
            parse_mode="HTML",
            reply_markup=admin_withdraw_item_kb(req.id),
        )


@router.message(F.text.func(lambda t: parse_withdraw_action(t) is not None))
async def msg_withdraw_action(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    parsed = parse_withdraw_action(message.text or "")
    if not parsed:
        return
    action, request_id = parsed
    approve = action == "approve"
    async with session_factory() as session:
        req = await set_withdrawal_admin_decision(session, request_id, approve=approve)
    if not req:
        await message.answer("Заявка не найдена.", reply_markup=admin_back_home_kb())
        return
    if req.admin_status != (
        WithdrawalAdminStatus.APPROVED if approve else WithdrawalAdminStatus.REJECTED
    ):
        await message.answer("Заявка уже обработана.", reply_markup=admin_back_home_kb())
        return
    verdict = "подтверждена" if approve else "отклонена"
    await message.answer(
        f"✅ Заявка ·#wd{req.id} {verdict}.",
        reply_markup=admin_back_home_kb(),
    )
    u = req.user
    if not u:
        return
    try:
        if approve:
            txt = (
                f"✅ Ваша заявка на вывод ·#wd{req.id} подтверждена администратором.\n"
                f"Сумма: {req.amount:.2f} ₽"
            )
        else:
            txt = (
                f"❌ Ваша заявка на вывод ·#wd{req.id} отклонена администратором.\n"
                f"Сумма: {req.amount:.2f} ₽"
            )
        await message.bot.send_message(u.telegram_id, txt)
    except (TelegramForbiddenError, TelegramBadRequest):
        pass

