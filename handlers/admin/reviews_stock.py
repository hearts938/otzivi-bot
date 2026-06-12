from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.formatting import blockquote
from handlers.keyboards import A_REVIEWS_STOCK, admin_root_kb
from services.reviews_stock import build_reviews_stock_message, fetch_platform_review_stock

router = Router(name="admin_reviews_stock")


@router.message(F.text == A_REVIEWS_STOCK)
async def msg_reviews_stock(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        rows = await fetch_platform_review_stock(session)
    text = build_reviews_stock_message(rows, settings)
    hint = blockquote(
        f"Автоматическая рассылка всем админам — каждый день в "
        f"{settings.reviews_stock_report_hour:02d}:"
        f"{settings.reviews_stock_report_minute:02d} ({settings.app_timezone})."
    )
    await message.answer(f"{text}\n\n{hint}", parse_mode="HTML", reply_markup=admin_root_kb())
