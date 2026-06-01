from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from config import Settings
from web.routes import router as admin_web_router


def create_app(
    settings: Settings,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.settings = settings
        if bot is not None:
            app.state.bot = bot
            app.state._owns_bot = False
        else:
            app.state.bot = Bot(
                settings.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            app.state._owns_bot = True
        yield
        if app.state._owns_bot:
            await app.state.bot.session.close()

    app = FastAPI(title="Bot admin", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.web_session_secret, session_cookie="abot_sess")
    app.include_router(admin_web_router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
