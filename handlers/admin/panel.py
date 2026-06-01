from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.admin.helpers import send_admin_home
from handlers.keyboards import BTN_ADMIN_HOME, BTN_CANCEL_INPUT, BTN_OPEN_ADMIN, BTN_USER_MENU
from handlers.menu_common import send_main_menu
from repo import ensure_user

router = Router(name="admin_panel")


@router.message(Command("admin"))
@router.message(F.text == BTN_OPEN_ADMIN)
async def cmd_admin(message: Message, settings: Settings, state: FSMContext):
    await send_admin_home(message, settings, state)


@router.message(F.text == BTN_ADMIN_HOME)
async def msg_admin_home(message: Message, settings: Settings, state: FSMContext):
    await send_admin_home(message, settings, state)


@router.message(F.text == BTN_CANCEL_INPUT)
async def msg_cancel(message: Message, settings: Settings, state: FSMContext):
    await send_admin_home(message, settings, state)


@router.message(F.text == BTN_USER_MENU)
async def msg_user_menu(
    message: Message,
    settings: Settings,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
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
    await send_main_menu(message, u, settings)
