from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import TaskText

logger = logging.getLogger(__name__)


async def activate_due_texts(session: AsyncSession) -> int:
    """Опубликовать тексты с наступившей датой, если такого текста ещё нет у заказчика."""
    from repo import task_text_body_exists

    now = datetime.utcnow()
    r = await session.execute(
        select(TaskText).where(
            TaskText.publish_at.is_not(None),
            TaskText.publish_at <= now,
            TaskText.published.is_(False),
            TaskText.taken_by_user_id.is_(None),
        )
    )
    activated = 0
    skipped = 0
    for tt in r.scalars().all():
        if await task_text_body_exists(session, tt.task_id, tt.body, exclude_id=tt.id):
            tt.publish_at = None
            skipped += 1
            continue
        tt.published = True
        activated += 1
    if activated or skipped:
        await session.commit()
    if skipped:
        logger.info("Пропущено дубликатов при публикации: %s", skipped)
    return activated


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
