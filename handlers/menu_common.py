from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import User
from handlers.admin.common import is_admin
from handlers.formatting import main_menu_text
from handlers.keyboards import user_main_kb
from repo import clear_ym_session, ensure_user


async def send_main_menu(message: Message, user: User, settings: Settings | None = None) -> None:
    bot = message.bot
    me = await bot.get_me()
    un = me.username or "bot"
    link = f"https://t.me/{un}?start=ref_{user.referral_code}"
    fu = message.from_user
    show_admin = bool(
        settings and fu and is_admin(fu.id, settings)
    )
    await message.answer(
        main_menu_text(user, link),
        reply_markup=user_main_kb(is_admin=show_admin),
        parse_mode="HTML",
    )


async def return_to_main_menu(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Сброс FSM/сессии Яндекс Карт и показ главного меню."""
    await state.clear()
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        await clear_ym_session(session, u.id)
    await send_main_menu(message, u, settings)
