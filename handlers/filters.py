from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repo import get_user_by_telegram


class OnboardingCompletedFilter(BaseFilter):
    async def __call__(
        self,
        event: TelegramObject,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> bool:
        uid: int | None = None
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
        else:
            uid = None
        if uid is None:
            return False
        async with session_factory() as session:
            u = await get_user_by_telegram(session, uid)
            return bool(u and u.onboarding_completed)
