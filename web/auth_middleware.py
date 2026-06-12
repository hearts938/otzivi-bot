"""Проверка серверных сессий веб-админки."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from services.web_admin_auth import get_web_admin_session, touch_web_admin_session


class WebAdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        sid = request.session.get("admin_sid")
        if sid:
            factory = getattr(request.app.state, "session_factory", None)
            if factory is not None:
                async with factory() as session:
                    row = await get_web_admin_session(session, sid)
                    if row is None:
                        request.session.pop("admin_sid", None)
                    else:
                        request.state.web_admin_session_id = sid
                        await touch_web_admin_session(session, sid)
                        await session.commit()
        response = await call_next(request)
        return response
