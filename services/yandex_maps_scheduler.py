from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datetime import datetime

from database.models import TaskText, User
from handlers.formatting import blockquote, section
from repo import (
    create_submission,
    get_task,
    list_due_yandex_reviews,
    save_ym_session,
)

logger = logging.getLogger(__name__)


async def process_yandex_review_deliveries(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession]
) -> int:
    sent = 0
    async with session_factory() as session:
        rows = await list_due_yandex_reviews(session)
    for ym in rows:
        try:
            async with session_factory() as session:
                u = ym.user
                if not u or not ym.task_text_id or not ym.task_id:
                    continue
                tt = await session.get(TaskText, ym.task_text_id)
                t = await get_task(session, ym.task_id)
                if not tt or not t:
                    continue
                sub = await create_submission(
                    session, u.id, t.id, tt.body, task_text_id=tt.id
                )
                if not sub:
                    continue
                reward = float(t.reward or 0)
                dbu = await session.get(User, u.id, with_for_update=True)
                if dbu:
                    dbu.pending_balance = float(dbu.pending_balance or 0) + reward
                ym.review_sent_at = datetime.utcnow()
                ym.submission_id = sub.id
                ym.step = "done"
                await save_ym_session(session, ym)
            instr = (t.description or "").strip()
            if instr:
                await bot.send_message(
                    u.telegram_id,
                    f"🗺 <b>Яндекс Карты — инструкция</b>\n\n{section('Инструкция', instr)}",
                    parse_mode="HTML",
                )
            await bot.send_message(
                u.telegram_id,
                f"🗺 <b>Текст отзыва</b>\n\n{blockquote(tt.body)}",
                parse_mode="HTML",
                protect_content=True,
            )
            await bot.send_message(
                u.telegram_id,
                f"✅ Текст отзыва выше. На баланс ожидания зачислено <b>{reward:.2f} ₽</b>. "
                f"После проверки и публикации сумма перейдёт в баланс к выплате.",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            logger.exception("yandex review delivery user=%s", getattr(ym, "user_id", None))
    return sent


async def yandex_maps_scheduler_loop(
    bot: Bot, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    while True:
        try:
            n = await process_yandex_review_deliveries(bot, session_factory)
            if n:
                logger.info("Яндекс Карты: отправлено текстов отзывов: %s", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка планировщика Яндекс Карт")
        await asyncio.sleep(60)
