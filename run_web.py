"""
Только веб-админка (бот в Telegram не запускается).
Сначала заполните WEB_* в .env. Для одного бота без сайта используйте main.py.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from config import get_settings
from database.session import init_db, make_engine, make_session_factory
from services.publish_scheduler import publish_scheduler_loop
from web.app import create_app

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    async def _boot() -> None:
        await init_db(engine, session_factory)
        asyncio.create_task(publish_scheduler_loop(session_factory))
        logger.info("База данных готова.")

    asyncio.run(_boot())
    app = create_app(settings, engine, session_factory, bot=None)
    uvicorn.run(
        app,
        host=settings.web_host,
        port=settings.web_port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
