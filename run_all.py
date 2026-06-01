"""
Бот + веб-админка вместе. Если нужен только Telegram — используйте main.py.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker
from uvicorn import Config, Server

from config import get_settings
from database.session import init_db, make_engine, make_session_factory
from handlers import (
    admin_router,
    onboarding_router,
    support_user_router,
    user_router,
    yandex_maps_router,
)
from services.publish_scheduler import publish_scheduler_loop
from services.yandex_maps_scheduler import yandex_maps_scheduler_loop
from web.app import create_app

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine, session_factory)
    asyncio.create_task(publish_scheduler_loop(session_factory))
    logger.info("База данных готова.")

    async def inject_session(_handler, event: TelegramObject, data: dict):
        data["session_factory"] = session_factory
        data["settings"] = settings
        return await _handler(event, data)

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    asyncio.create_task(yandex_maps_scheduler_loop(bot, session_factory))
    dp = Dispatcher()
    dp.update.outer_middleware(inject_session)
    dp.include_router(onboarding_router)
    dp.include_router(admin_router)
    dp.include_router(support_user_router)
    dp.include_router(yandex_maps_router)
    dp.include_router(user_router)

    app = create_app(settings, engine, session_factory, bot=bot)
    server = Server(
        Config(
            app,
            host=settings.web_host,
            port=settings.web_port,
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    )

    try:
        await asyncio.gather(server.serve(), dp.start_polling(bot))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
