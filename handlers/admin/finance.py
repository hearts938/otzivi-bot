from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.formatting import blockquote, section
from handlers.keyboards import (
    A_FINANCE,
    BTN_ADMIN_HOME,
    BTN_BACK_FIN,
    admin_back_home_kb,
    admin_labeled_list_kb,
    _kb,
    _rows,
    finance_platform_label,
    parse_finance_platform,
)
from services.admin_stats import list_platforms, platform_snapshot

router = Router(name="admin_finance")


@router.message(F.text == A_FINANCE)
@router.message(F.text == BTN_BACK_FIN)
async def msg_fin_menu(message: Message, session_factory: async_sessionmaker[AsyncSession], settings: Settings):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        pls = await list_platforms(session)
    if not pls:
        await message.answer("Нет сервисов.", reply_markup=admin_back_home_kb())
        return
    labels = [finance_platform_label(p.id, p.name) for p in pls]
    await message.answer(
        f"💰 <b>Финансовая панель</b>\n\n{blockquote('Выберите сервис.')}",
        reply_markup=admin_labeled_list_kb(labels, [BTN_BACK_FIN, BTN_ADMIN_HOME]),
        parse_mode="HTML",
    )


@router.message(F.text.func(lambda t: parse_finance_platform(t) is not None))
async def msg_fin_platform(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_finance_platform(message.text or "")
    if pid is None:
        return
    async with session_factory() as session:
        snap = await platform_snapshot(session, pid)
    if not snap:
        await message.answer("Нет данных.", reply_markup=admin_back_home_kb())
        return
    top_lines = "\n".join(
        f"{i+1}) ID <code>{tg}</code> @{un or '—'} — {amt:.2f} ₽ ({cnt} шт.)"
        for i, (tg, un, amt, cnt) in enumerate(snap.top5)
    ) or "—"
    body = (
        f"Slug: <code>{snap.platform.slug}</code>\n\n"
        f"Всё время: {snap.completed_all} шт., {snap.cost_all:.2f} ₽\n"
        f"Сегодня: {snap.completed_today} шт., {snap.cost_today:.2f} ₽\n\n"
        f"Топ-5:\n{top_lines}"
    )
    await message.answer(
        f"💰 <b>{snap.platform.name}</b>\n\n{section('Статистика', body)}",
        parse_mode="HTML",
        reply_markup=_kb(_rows(BTN_BACK_FIN, BTN_ADMIN_HOME)),
    )
