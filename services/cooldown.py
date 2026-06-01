from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Submission, SubmissionStatus


async def release_expired_cooldowns(session: AsyncSession) -> int:
    now = datetime.utcnow()
    res = await session.execute(
        update(Submission)
        .where(
            Submission.status == SubmissionStatus.COOLDOWN,
            Submission.cooldown_until.is_not(None),
            Submission.cooldown_until <= now,
        )
        .values(status=SubmissionStatus.PENDING)
    )
    await session.commit()
    return res.rowcount or 0


def compute_cooldown_until(seconds: int) -> datetime | None:
    if seconds <= 0:
        return None
    return datetime.utcnow() + timedelta(seconds=seconds)
