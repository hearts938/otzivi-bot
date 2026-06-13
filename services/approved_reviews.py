"""Подтверждённые админом отзывы: статистика и выгрузка Excel."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Platform, Submission, SubmissionStatus, Task, User
from services.gender import gender_label


def _approval_ts():
    return func.coalesce(Submission.approved_at, Submission.completed_at, Submission.created_at)


def parse_admin_date(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def day_range_to_utc(date_from: date, date_to: date, tz_name: str) -> tuple[datetime, datetime]:
    from zoneinfo import ZoneInfo

    if date_to < date_from:
        date_from, date_to = date_to, date_from
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(date_from, time.min, tzinfo=tz)
    end_local = datetime.combine(date_to, time(23, 59, 59, 999999), tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


def utc_now_in_tz(tz_name: str) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(tz_name))


@dataclass
class ApprovedReviewRow:
    id: int
    approved_at: datetime | None
    city: str
    gender: str
    text: str
    link: str
    customer_name: str
    platform_name: str
    username: str | None
    telegram_id: int


@dataclass
class ApprovedReviewStats:
    total: int
    today: int
    last_7_days: int
    last_30_days: int


def _format_dt(dt: datetime | None, tz_name: str) -> str:
    if not dt:
        return "—"
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


def _row_from_submission(sub: Submission) -> ApprovedReviewRow:
    u: User | None = sub.user
    t: Task | None = sub.task
    city = "—"
    link = "—"
    customer = "—"
    platform_name = "—"
    if t:
        city = (t.region or "").strip() or (u.work_region if u else "") or "—"
        link = (t.link or "").strip() or "—"
        customer = (t.customer_name or t.title or "").strip() or "—"
        pf: Platform | None = getattr(t, "platform", None)
        if pf:
            platform_name = pf.name or "—"
    elif u and u.work_region:
        city = u.work_region.strip()
    ts = sub.approved_at or sub.completed_at or sub.created_at
    return ApprovedReviewRow(
        id=sub.id,
        approved_at=ts,
        city=city,
        gender=gender_label(u.gender if u else None),
        text=(sub.review_text or "").strip(),
        link=link,
        customer_name=customer,
        platform_name=platform_name,
        username=u.username if u else None,
        telegram_id=int(u.telegram_id) if u else 0,
    )


async def _count_approved_between(
    session: AsyncSession, start: datetime | None, end: datetime | None
) -> int:
    ts = _approval_ts()
    q = select(func.count()).select_from(Submission).where(
        Submission.status == SubmissionStatus.APPROVED
    )
    if start is not None:
        q = q.where(ts >= start)
    if end is not None:
        q = q.where(ts <= end)
    r = await session.execute(q)
    return int(r.scalar_one() or 0)


async def fetch_approved_review_stats(
    session: AsyncSession, *, tz_name: str
) -> ApprovedReviewStats:
    now_local = utc_now_in_tz(tz_name)
    today = now_local.date()
    start_today, end_today = day_range_to_utc(today, today, tz_name)
    start_7, _ = day_range_to_utc(today - timedelta(days=6), today, tz_name)
    start_30, _ = day_range_to_utc(today - timedelta(days=29), today, tz_name)
    total = await _count_approved_between(session, None, None)
    today_n = await _count_approved_between(session, start_today, end_today)
    d7 = await _count_approved_between(session, start_7, end_today)
    d30 = await _count_approved_between(session, start_30, end_today)
    return ApprovedReviewStats(total=total, today=today_n, last_7_days=d7, last_30_days=d30)


async def list_approved_reviews(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    tz_name: str = "Europe/Moscow",
    limit: int = 5000,
) -> list[ApprovedReviewRow]:
    ts = _approval_ts()
    q = (
        select(Submission)
        .where(Submission.status == SubmissionStatus.APPROVED)
        .options(
            selectinload(Submission.user),
            selectinload(Submission.task).selectinload(Task.platform),
        )
        .order_by(ts.desc())
        .limit(max(1, min(int(limit), 10000)))
    )
    if date_from and date_to:
        start, end = day_range_to_utc(date_from, date_to, tz_name)
        q = q.where(ts >= start, ts <= end)
    r = await session.execute(q)
    return [_row_from_submission(s) for s in r.scalars().unique().all()]


def build_approved_reviews_xlsx(rows: list[ApprovedReviewRow], *, tz_name: str) -> bytes:
    data = [
        {
            "Дата одобрения": _format_dt(row.approved_at, tz_name),
            "Город": row.city,
            "Пол": row.gender,
            "Текст": row.text,
            "Ссылка": row.link,
        }
        for row in rows
    ]
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def approved_stats_text(stats: ApprovedReviewStats) -> str:
    return (
        f"Всего подтверждено: <b>{stats.total}</b>\n"
        f"Сегодня: <b>{stats.today}</b>\n"
        f"За 7 дней: <b>{stats.last_7_days}</b>\n"
        f"За 30 дней: <b>{stats.last_30_days}</b>"
    )
