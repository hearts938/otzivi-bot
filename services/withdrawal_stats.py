"""Статистика выплат (заявки на вывод) для админки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import WithdrawalRequest, WithdrawalStatus

SUCCESS_STATUSES = frozenset({
    WithdrawalStatus.CREATED,
    WithdrawalStatus.EXECUTED,
    WithdrawalStatus.MANUALPAY,
})


@dataclass(frozen=True)
class WithdrawalPeriodStats:
    key: str
    label: str
    total_count: int
    total_amount: float
    success_count: int
    success_amount: float
    failed_count: int
    failed_amount: float


def _utc_naive_from_local_start(day, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    local = datetime.combine(day, time(0, 0), tzinfo=tz)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def withdrawal_period_starts(tz_name: str) -> dict[str, datetime | None]:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    today = now_local.date()
    return {
        "today": _utc_naive_from_local_start(today, tz_name),
        "week": _utc_naive_from_local_start(today - timedelta(days=6), tz_name),
        "month": _utc_naive_from_local_start(today.replace(day=1), tz_name),
        "all": None,
    }


async def aggregate_withdrawals(
    session: AsyncSession,
    since: datetime | None,
) -> tuple[int, float, int, float, int, float]:
    success_cond = WithdrawalRequest.status.in_(tuple(SUCCESS_STATUSES))
    failed_cond = WithdrawalRequest.status == WithdrawalStatus.FAILED
    stmt = select(
        func.count(WithdrawalRequest.id),
        func.coalesce(func.sum(WithdrawalRequest.amount), 0.0),
        func.coalesce(func.sum(case((success_cond, 1), else_=0)), 0),
        func.coalesce(func.sum(case((success_cond, WithdrawalRequest.amount), else_=0.0)), 0.0),
        func.coalesce(func.sum(case((failed_cond, 1), else_=0)), 0),
        func.coalesce(func.sum(case((failed_cond, WithdrawalRequest.amount), else_=0.0)), 0.0),
    )
    if since is not None:
        stmt = stmt.where(WithdrawalRequest.created_at >= since)
    row = (await session.execute(stmt)).one()
    return (
        int(row[0] or 0),
        float(row[1] or 0),
        int(row[2] or 0),
        float(row[3] or 0),
        int(row[4] or 0),
        float(row[5] or 0),
    )


async def fetch_withdrawal_stats(
    session: AsyncSession,
    tz_name: str,
) -> list[WithdrawalPeriodStats]:
    labels = {
        "today": "Сегодня",
        "week": "За 7 дней",
        "month": "За месяц",
        "all": "Всё время",
    }
    starts = withdrawal_period_starts(tz_name)
    out: list[WithdrawalPeriodStats] = []
    for key in ("today", "week", "month", "all"):
        total_count, total_amount, success_count, success_amount, failed_count, failed_amount = (
            await aggregate_withdrawals(session, starts[key])
        )
        out.append(
            WithdrawalPeriodStats(
                key=key,
                label=labels[key],
                total_count=total_count,
                total_amount=total_amount,
                success_count=success_count,
                success_amount=success_amount,
                failed_count=failed_count,
                failed_amount=failed_amount,
            )
        )
    return out


def format_withdrawal_stats_message(periods: list[WithdrawalPeriodStats], tz_name: str) -> str:
    blocks: list[str] = []
    for p in periods:
        blocks.append(
            f"<b>{p.label}</b>\n"
            f"✅ Успешно: <b>{p.success_count}</b> шт. · <b>{p.success_amount:.2f}</b> ₽\n"
            f"❌ Ошибки: <b>{p.failed_count}</b> шт. · <b>{p.failed_amount:.2f}</b> ₽\n"
            f"Всего попыток: <b>{p.total_count}</b> шт. · <b>{p.total_amount:.2f}</b> ₽"
        )
    body = "\n\n".join(blocks)
    return (
        f"📊 <b>Статистика выплат</b>\n\n"
        f"<blockquote>{body}</blockquote>\n\n"
        f"<i>Периоды по часовому поясу {tz_name}. «За месяц» — с 1-го числа.</i>"
    )
