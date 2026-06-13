from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware

import asyncio

from config import Settings
from services.reviews_stock import reviews_stock_scheduler_loop
from services.web_admin_auth import ensure_password_initialized
from web.auth_middleware import WebAdminAuthMiddleware
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
        async with session_factory() as session:
            await ensure_password_initialized(session, settings)
            await session.commit()
        asyncio.create_task(reviews_stock_scheduler_loop(app.state.bot, session_factory))
        yield
        if app.state._owns_bot:
            await app.state.bot.session.close()

    templates_dir = Path(__file__).resolve().parent / "templates"
    import_templates = Jinja2Templates(directory=str(templates_dir))

    app = FastAPI(title="Bot admin", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def import_validation_error(request: Request, exc: RequestValidationError):
        if request.method == "POST" and request.url.path == "/import":
            tz = settings.app_timezone
            return import_templates.TemplateResponse(
                "import_texts.html",
                {
                    "request": request,
                    "msg": None,
                    "err": (
                        "Файл не дошёл до сервера. Выберите .xlsx "
                        "и нажмите «Загрузить и импортировать»."
                    ),
                    "warnings": None,
                    "timezone": tz,
                },
                status_code=400,
            )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    app.add_middleware(WebAdminAuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=settings.web_session_secret, session_cookie="abot_sess")
    app.include_router(admin_web_router)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app
