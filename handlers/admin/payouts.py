from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.admin.states import AdminPayoutsBrowse
from handlers.formatting import blockquote
from handlers.keyboards import (
    A_PAYOUTS,
    BTN_ADMIN_HOME,
    BTN_PAYOUT_RECENT,
    BTN_PAYOUT_SEARCH,
    PAYOUTS_PAGE_SIZE,
    admin_back_home_kb,
    admin_payouts_list_kb,
    admin_payouts_menu_kb,
    parse_payout_pick,
    payout_pick_label,
)
from repo import get_withdrawal, list_withdrawals, resolve_user_ref
from services.payout_registry import format_payout_card_html, parse_payout_ref

router = Router(name="admin_payouts")


async def _send_payout_card(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    payout_id: int,
) -> bool:
    async with session_factory() as session:
        req = await get_withdrawal(session, payout_id)
    if not req:
        await message.answer("Выплата не найдена.", reply_markup=admin_back_home_kb())
        return False
    await message.answer(
        format_payout_card_html(req, settings.app_timezone),
        parse_mode="HTML",
        reply_markup=admin_payouts_menu_kb(),
    )
    return True


async def _send_payout_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int | None = None,
    header: str,
) -> None:
    async with session_factory() as session:
        rows = await list_withdrawals(
            session, limit=PAYOUTS_PAGE_SIZE, user_id=user_id
        )
    if not rows:
        await message.answer(
            f"{header}\n\n{blockquote('Выплат пока нет.')}",
            parse_mode="HTML",
            reply_markup=admin_payouts_menu_kb(),
        )
        return
    labels = [
        payout_pick_label(
            r.id,
            r.user.username if r.user else None,
            float(r.amount or 0),
        )
        for r in rows
    ]
    await message.answer(
        f"{header}\n\n{blockquote('Нажмите выплату для подробностей или введите номер: #wd5')}",
        parse_mode="HTML",
        reply_markup=admin_payouts_list_kb(labels),
    )


@router.message(F.text == A_PAYOUTS)
async def msg_payouts_menu(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await message.answer(
        f"📒 <b>Реестр выплат</b>\n\n"
        f"{blockquote('Каждая выплата имеет номер ·#wdN. Поиск: @username, Telegram ID или номер (#wd5, wd5).')}",
        parse_mode="HTML",
        reply_markup=admin_payouts_menu_kb(),
    )


@router.message(F.text == BTN_PAYOUT_RECENT)
async def msg_payouts_recent(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await _send_payout_list(
        message,
        session_factory,
        header="📋 <b>Последние выплаты</b>",
    )


@router.message(F.text == BTN_PAYOUT_SEARCH)
async def msg_payouts_search_start(
    message: Message, settings: Settings, state: FSMContext
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(AdminPayoutsBrowse.search_user)
    await message.answer(
        f"🔍 <b>Поиск выплат</b>\n\n"
        f"{blockquote('Введите @username, Telegram ID или номер выплаты (#wd5, wd5).')}",
        parse_mode="HTML",
        reply_markup=admin_back_home_kb(),
    )


@router.message(AdminPayoutsBrowse.search_user, F.text)
async def msg_payouts_search_user(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    if message.text == BTN_ADMIN_HOME:
        await state.clear()
        return
    ref = (message.text or "").strip()
    pid = parse_payout_ref(ref)
    if pid is not None:
        await state.clear()
        await _send_payout_card(message, session_factory, settings, pid)
        return
    async with session_factory() as session:
        u = await resolve_user_ref(session, ref)
    if not u:
        await message.answer(
            "Не найдено. Введите @username, Telegram ID или номер выплаты (#wd5, wd5).",
            reply_markup=admin_back_home_kb(),
        )
        return
    un = f"@{u.username}" if u.username else f"ID {u.telegram_id}"
    await state.clear()
    await _send_payout_list(
        message,
        session_factory,
        user_id=u.id,
        header=f"📒 <b>Выплаты пользователя {un}</b>",
    )


@router.message(F.text.func(lambda t: parse_payout_pick(t) is not None))
async def msg_payout_pick(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_payout_pick(message.text)
    if pid is None:
        return
    await _send_payout_card(message, session_factory, settings, pid)


@router.message(F.text.func(lambda t: parse_payout_ref(t) is not None))
async def msg_payout_by_number(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_payout_ref(message.text)
    if pid is None:
        return
    await _send_payout_card(message, session_factory, settings, pid)
