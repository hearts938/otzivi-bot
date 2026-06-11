"""Тест Яндекс Карт: случайные вопросы и античит."""

from __future__ import annotations

import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import YandexMapsQuestion, YandexMapsSession
from repo import list_yandex_questions_by_order
from services.yandex_maps import YANDEX_QUIZ_POOL_SIZE, format_question_order


def answer_is_too_fast(shown_at: datetime | None, min_seconds: int) -> bool:
    if not shown_at or min_seconds <= 0:
        return False
    elapsed = (datetime.utcnow() - shown_at).total_seconds()
    return elapsed < float(min_seconds)


async def pick_random_quiz_slots(
    session: AsyncSession,
    *,
    count: int = YANDEX_QUIZ_POOL_SIZE,
) -> list[int] | None:
    r = await session.execute(
        select(YandexMapsQuestion.slot).where(YandexMapsQuestion.active.is_(True))
    )
    slots = [int(row[0]) for row in r.all()]
    if len(slots) < count:
        return None
    return random.sample(slots, count)


async def list_yandex_questions_for_ym_session(
    session: AsyncSession,
    ym: YandexMapsSession | None,
) -> list[YandexMapsQuestion]:
    if not ym or not (ym.quiz_slots or "").strip():
        return []
    parts = [p.strip() for p in ym.quiz_slots.split(",") if p.strip()]
    try:
        order = [int(p) for p in parts]
    except ValueError:
        return []
    if not order:
        return []
    return await list_yandex_questions_by_order(session, format_question_order(order))
