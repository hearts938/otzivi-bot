from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from database.models import Platform
from handlers.keyboards import parse_user_platform_pick
from services.yandex_maps import is_yandex_maps_slug


class YandexPlatformPickFilter(BaseFilter):
    async def __call__(self, message: Message, session_factory: async_sessionmaker) -> bool:
        pid = parse_user_platform_pick(message.text)
        if pid is None or session_factory is None:
            return False
        async with session_factory() as session:
            p = await session.get(Platform, pid)
        return p is not None and is_yandex_maps_slug(p.slug)
