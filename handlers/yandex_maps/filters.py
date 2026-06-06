from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import Platform
from handlers.keyboards import parse_user_platform_pick
from repo import ensure_user, get_active_ym_session, INCOMPLETE_YM_STEPS
from services.yandex_maps import is_yandex_maps_slug


class YandexPlatformPickFilter(BaseFilter):
    async def __call__(self, message: Message, session_factory: async_sessionmaker) -> bool:
        pid = parse_user_platform_pick(message.text)
        if pid is None or session_factory is None:
            return False
        async with session_factory() as session:
            p = await session.get(Platform, pid)
        return p is not None and is_yandex_maps_slug(p.slug)


class ActiveYandexFlowFilter(BaseFilter):
    """Есть незавершённая сессия Яндекс Карт (не «заморозка» после теста)."""

    async def __call__(self, message: Message, session_factory: async_sessionmaker) -> bool:
        if session_factory is None or not message.from_user:
            return False
        async with session_factory() as session:
            u = await ensure_user(
                session,
                message.from_user.id,
                message.from_user.username,
                referred_by_id=None,
            )
            ym = await get_active_ym_session(session, u.id)
        return ym is not None and ym.step in INCOMPLETE_YM_STEPS
