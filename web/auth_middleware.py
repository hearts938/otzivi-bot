"""Проверка серверных сессий веб-админки."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from services.web_admin_auth import client_ip_from_headers, sync_admin_session_from_cookie


class WebAdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.session.get("admin"):
            factory = getattr(request.app.state, "session_factory", None)
            if factory is not None:
                async with factory() as db:
                    row = await sync_admin_session_from_cookie(
                        db,
                        session_id=request.session.get("admin_sid"),
                        ip_address=client_ip_from_headers(
                            forwarded_for=request.headers.get("x-forwarded-for"),
                            client_host=request.client.host if request.client else None,
                        ),
                        user_agent=request.headers.get("user-agent"),
                    )
                    if row is None:
                        request.session.pop("admin", None)
                        request.session.pop("admin_sid", None)
                    else:
                        request.session["admin_sid"] = row.id
                        request.state.web_admin_session_id = row.id
                        await db.commit()
        response = await call_next(request)
        return response
