from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import TaskText

logger = logging.getLogger(__name__)


async def activate_due_texts(session: AsyncSession) -> int:
    now = datetime.utcnow()
    res = await session.execute(
        update(TaskText)
        .where(
            TaskText.publish_at.is_not(None),
            TaskText.publish_at <= now,
            TaskText.published.is_(False),
        )
        .values(published=True)
    )
    await session.commit()
    return res.rowcount or 0


async def publish_scheduler_loop(session_factory: async_sessionmaker[AsyncSession]) -> None:
    from config import get_settings
    from repo import release_expired_task_claims

    settings = get_settings()
    while True:
        try:
            async with session_factory() as session:
                n = await activate_due_texts(session)
                if n:
                    logger.info("Опубликовано текстов: %s", n)
                expired = await release_expired_task_claims(
                    session, settings.task_claim_minutes
                )
                if expired:
                    logger.info("Снято просроченных броней: %s", expired)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка планировщика публикации")
        await asyncio.sleep(60)
