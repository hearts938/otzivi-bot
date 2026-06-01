from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Platform, Submission, SubmissionStatus, Task, User


def _utc_day_start() -> datetime:
    n = datetime.utcnow()
    return datetime(n.year, n.month, n.day)


@dataclass
class PlatformFinanceSnapshot:
    platform: Platform
    completed_all: int
    cost_all: float
    completed_today: int
    cost_today: float
    top5: list[tuple[int, str | None, float, int]]


async def list_platforms(session: AsyncSession) -> list[Platform]:
    r = await session.execute(select(Platform).order_by(Platform.id.asc()))
    return list(r.scalars().all())


async def platform_snapshot(session: AsyncSession, platform_id: int) -> PlatformFinanceSnapshot | None:
    pf = await session.get(Platform, platform_id)
    if not pf:
        return None

    subq_time = func.coalesce(Submission.approved_at, Submission.created_at)

    q_all = await session.execute(
        select(func.count(Submission.id), func.coalesce(func.sum(Task.reward), 0.0))
        .select_from(Submission)
        .join(Task, Task.id == Submission.task_id)
        .where(
            Task.platform_id == platform_id,
            Submission.status == SubmissionStatus.APPROVED,
        )
    )
    completed_all, cost_all = q_all.one()

    today = _utc_day_start()
    q_today = await session.execute(
        select(func.count(Submission.id), func.coalesce(func.sum(Task.reward), 0.0))
        .select_from(Submission)
        .join(Task, Task.id == Submission.task_id)
        .where(
            Task.platform_id == platform_id,
            Submission.status == SubmissionStatus.APPROVED,
            subq_time >= today,
        )
    )
    completed_today, cost_today = q_today.one()

    top_stmt = (
        select(
            User.telegram_id,
            User.username,
            func.sum(Task.reward),
            func.count(Submission.id),
        )
        .join(Submission, Submission.user_id == User.id)
        .join(Task, Task.id == Submission.task_id)
        .where(
            Task.platform_id == platform_id,
            Submission.status == SubmissionStatus.APPROVED,
        )
        .group_by(User.id)
        .order_by(func.sum(Task.reward).desc())
        .limit(5)
    )
    top_rows = (await session.execute(top_stmt)).all()
    top5 = [(int(r[0]), r[1], float(r[2]), int(r[3])) for r in top_rows]

    return PlatformFinanceSnapshot(
        platform=pf,
        completed_all=int(completed_all or 0),
        cost_all=float(cost_all or 0.0),
        completed_today=int(completed_today or 0),
        cost_today=float(cost_today or 0.0),
        top5=top5,
    )


async def count_user_approved_in_range(
    session: AsyncSession, user_id: int, start: datetime
) -> int:
    subq_time = func.coalesce(Submission.approved_at, Submission.created_at)
    q = await session.execute(
        select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.APPROVED,
            subq_time >= start,
        )
    )
    return int(q.scalar_one() or 0)


async def user_activity_bundle(session: AsyncSession, user_id: int) -> tuple[int, int, int]:
    now = datetime.utcnow()
    day0 = datetime(now.year, now.month, now.day)
    w0 = now - timedelta(days=7)
    m0 = now - timedelta(days=30)
    d = await count_user_approved_in_range(session, user_id, day0)
    w = await count_user_approved_in_range(session, user_id, w0)
    m = await count_user_approved_in_range(session, user_id, m0)
    return d, w, m
