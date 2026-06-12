from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.admin.states import AdminUsersBrowse
from handlers.formatting import (
    admin_user_card_text,
    blockquote,
    section,
    users_admin_list_text,
    users_admin_summary_text,
)
from handlers.keyboards import (
    A_USERS_LIST,
    A_USERS_MGMT,
    A_USERS_SUM,
    BAN_TOGGLE_LABELS,
    BTN_ADMIN_HOME,
    BTN_BACK_USER_LIST,
    BTN_BACK_USERS_MENU,
    BTN_PAGE_NEXT,
    BTN_PAGE_PREV,
    USERS_PAGE_SIZE,
    admin_back_home_kb,
    admin_user_card_kb,
    admin_users_menu_kb,
    admin_users_page_kb,
    parse_user_pick_telegram_id,
    user_pick_label,
)
from repo import (
    count_approved_submissions,
    count_users,
    get_user_by_id,
    get_user_by_telegram,
    list_users_admin_page,
    set_user_banned,
    user_is_banned_now,
)
from services.admin_stats import user_activity_bundle

router = Router(name="admin_users")

_USERS_BACK = [BTN_BACK_USERS_MENU, BTN_ADMIN_HOME]


async def _show_users_summary_page(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    page: int,
) -> None:
    async with session_factory() as session:
        total = await count_users(session)
        pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
        page = max(0, min(page, pages - 1))
        users = await list_users_admin_page(session, page * USERS_PAGE_SIZE, USERS_PAGE_SIZE)
        lines: list[str] = []
        for u in users:
            c = await count_approved_submissions(session, u.id)
            un = f"@{u.username}" if u.username else "без username"
            lines.append(
                f"• {un} · ID <code>{u.telegram_id}</code>\n"
                f"  баланс {u.balance:.2f} · заданий {c}"
            )
    await state.set_state(AdminUsersBrowse.summary)
    await state.update_data(users_page=page)
    text = users_admin_summary_text(lines, page=page, pages=pages, total=total)
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=admin_users_page_kb(
            None,
            show_prev=page > 0,
            show_next=page < pages - 1,
            back_nav=_USERS_BACK,
        ),
    )


async def _show_users_list_page(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    page: int,
) -> None:
    async with session_factory() as session:
        total = await count_users(session)
        if total == 0:
            await state.clear()
            await message.answer("Пользователей нет.", reply_markup=admin_back_home_kb())
            return
        pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
        page = max(0, min(page, pages - 1))
        users = await list_users_admin_page(session, page * USERS_PAGE_SIZE, USERS_PAGE_SIZE)
    labels = [user_pick_label(u.username, u.telegram_id, user_is_banned_now(u)) for u in users]
    await state.set_state(AdminUsersBrowse.list_pick)
    await state.update_data(users_page=page)
    await message.answer(
        users_admin_list_text(page=page, pages=pages, total=total),
        reply_markup=admin_users_page_kb(
            labels,
            show_prev=page > 0,
            show_next=page < pages - 1,
            back_nav=_USERS_BACK,
        ),
        parse_mode="HTML",
    )


@router.message(F.text == A_USERS_SUM)
async def msg_users_summary(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await _show_users_summary_page(message, session_factory, state, 0)


@router.message(F.text == A_USERS_MGMT)
@router.message(F.text == BTN_BACK_USERS_MENU)
async def msg_users_menu(
    message: Message,
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await message.answer(
        f"👥 <b>Управление пользователями</b>\n\n"
        f"{blockquote('Сводка — постранично. Список — карточка и бан.')}",
        parse_mode="HTML",
        reply_markup=admin_users_menu_kb(),
    )


@router.message(F.text == A_USERS_LIST)
@router.message(F.text == BTN_BACK_USER_LIST)
async def msg_users_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await _show_users_list_page(message, session_factory, state, 0)


@router.message(AdminUsersBrowse.summary, F.text == BTN_PAGE_PREV)
@router.message(AdminUsersBrowse.summary, F.text == BTN_PAGE_NEXT)
async def msg_users_summary_page(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    data = await state.get_data()
    page = int(data.get("users_page", 0))
    if message.text == BTN_PAGE_PREV:
        page = max(0, page - 1)
    else:
        page += 1
    await _show_users_summary_page(message, session_factory, state, page)


@router.message(AdminUsersBrowse.list_pick, F.text == BTN_PAGE_PREV)
@router.message(AdminUsersBrowse.list_pick, F.text == BTN_PAGE_NEXT)
async def msg_users_list_page(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    data = await state.get_data()
    page = int(data.get("users_page", 0))
    if message.text == BTN_PAGE_PREV:
        page = max(0, page - 1)
    else:
        page += 1
    await _show_users_list_page(message, session_factory, state, page)


@router.message(F.text.func(lambda t: parse_user_pick_telegram_id(t) is not None))
async def msg_user_card(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    tg_id = parse_user_pick_telegram_id(message.text or "")
    if tg_id is None:
        return
    async with session_factory() as session:
        u = await get_user_by_telegram(session, tg_id)
        if not u:
            await message.answer("Не найден.", reply_markup=admin_back_home_kb())
            return
        done = await count_approved_submissions(session, u.id)
        d_act, w_act, m_act = await user_activity_bundle(session, u.id)
    await state.update_data(view_user_id=u.id)
    await message.answer(
        admin_user_card_text(u, done, d_act, w_act, m_act),
        parse_mode="HTML",
        reply_markup=admin_user_card_kb(user_is_banned_now(u)),
    )


@router.message(F.text.in_(BAN_TOGGLE_LABELS))
async def msg_ban_toggle(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    data = await state.get_data()
    uid = data.get("view_user_id")
    if not uid:
        await message.answer("Сначала выберите пользователя из списка.")
        return
    async with session_factory() as session:
        u = await get_user_by_id(session, int(uid))
        if not u:
            await message.answer("Не найден.")
            return
        new_b = not user_is_banned_now(u)
        await set_user_banned(session, int(uid), new_b)
        u = await get_user_by_id(session, int(uid))
    if u:
        notify = (
            "🚫 <b>Аккаунт заблокирован</b>\n\n"
            f"{blockquote('Администратор ограничил доступ. Задания и другие разделы недоступны.')}"
            if new_b
            else "✅ <b>Аккаунт разблокирован</b>\n\n"
            f"{blockquote('Доступ восстановлен. Снова доступны все разделы бота.')}"
        )
        try:
            await message.bot.send_message(u.telegram_id, notify, parse_mode="HTML")
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
    await message.answer(
        f"{'🚫 Пользователь заблокирован' if new_b else '✅ Пользователь разблокирован'}\n\n"
        f"{section('Telegram ID', str(u.telegram_id if u else '—'))}",
        parse_mode="HTML",
        reply_markup=admin_user_card_kb(user_is_banned_now(u)) if u else admin_back_home_kb(),
    )
    if u:
        await state.update_data(view_user_id=u.id)
