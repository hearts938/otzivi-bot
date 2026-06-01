from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from handlers.admin.common import is_admin
from handlers.formatting import admin_home_text
from handlers.keyboards import admin_root_kb


async def send_admin_home(message: Message, settings: Settings, state: FSMContext) -> bool:
    if not is_admin(message.from_user.id, settings):
        await message.answer("Нет доступа.")
        return False
    await state.clear()
    await message.answer(
        admin_home_text(message.from_user),
        reply_markup=admin_root_kb(),
        parse_mode="HTML",
    )
    return True
