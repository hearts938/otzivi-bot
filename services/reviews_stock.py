"""Остатки отзывов в пуле по платформам — отчёт админам."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from database.models import Platform, Task, TaskText
from handlers.formatting import blockquote, esc_html

logger = logging.getLogger(__name__)


@dataclass
class PlatformReviewStock:
    platform_id: int
    platform_name: str
    free_total: int
    free_male: int
    free_female: int
    in_work: int
    scheduled: int


async def fetch_platform_review_stock(session: AsyncSession) -> list[PlatformReviewStock]:
    """Свободные тексты в пуле, в работе и ожидающие публикации по платформам."""
    now = datetime.utcnow()
    free_cond = and_(
        TaskText.taken_by_user_id.is_(None),
        TaskText.published.is_(True),
        or_(TaskText.publish_at.is_(None), TaskText.publish_at <= now),
    )
    scheduled_cond = and_(
        TaskText.published.is_(False),
        TaskText.publish_at.is_not(None),
        TaskText.publish_at > now,
    )
    r = await session.execute(
        select(
            Platform.id,
            Platform.name,
            func.coalesce(
                func.sum(case((free_cond, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (and_(free_cond, TaskText.required_gender == "male"), 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (and_(free_cond, TaskText.required_gender == "female"), 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((TaskText.taken_by_user_id.is_not(None), 1), else_=0)),
                0,
            ),
            func.coalesce(func.sum(case((scheduled_cond, 1), else_=0)), 0),
        )
        .select_from(Platform)
        .join(Task, Task.platform_id == Platform.id)
        .join(TaskText, TaskText.task_id == Task.id)
        .where(Platform.active.is_(True), Task.active.is_(True))
        .group_by(Platform.id, Platform.name)
        .order_by(Platform.name.asc())
    )
    out: list[PlatformReviewStock] = []
    for pid, name, free, fm, ff, taken, sched in r.all():
        out.append(
            PlatformReviewStock(
                platform_id=int(pid),
                platform_name=str(name),
                free_total=int(free or 0),
                free_male=int(fm or 0),
                free_female=int(ff or 0),
                in_work=int(taken or 0),
                scheduled=int(sched or 0),
            )
        )
    return out


def _report_title(settings: Settings) -> str:
    tz = ZoneInfo(settings.app_timezone)
    now_local = datetime.now(tz)
    return (
        f"📊 <b>Детализация по отзывам</b>\n"
        f"<i>{now_local.strftime('%d.%m.%Y %H:%M')} ({esc_html(settings.app_timezone)})</i>"
    )


def build_reviews_stock_message(rows: list[PlatformReviewStock], settings: Settings) -> str:
    if not rows:
        return (
            f"{_report_title(settings)}\n\n"
            f"{blockquote('Нет активных платформ с текстами в пуле.')}"
        )
    lines: list[str] = [_report_title(settings), ""]
    total_free = 0
    total_work = 0
    total_sched = 0
    for row in rows:
        total_free += row.free_total
        total_work += row.in_work
        total_sched += row.scheduled
        lines.append(f"🌐 <b>{esc_html(row.platform_name)}</b>")
        lines.append(
            f"Свободно: <b>{row.free_total}</b> "
            f"(М: {row.free_male}, Ж: {row.free_female})"
        )
        if row.in_work:
            lines.append(f"В работе у исполнителей: <b>{row.in_work}</b>")
        if row.scheduled:
            lines.append(f"Скоро выйдут по расписанию: <b>{row.scheduled}</b>")
        lines.append("")
    lines.append(
        f"<b>Итого свободно:</b> {total_free} · "
        f"<b>в работе:</b> {total_work} · "
        f"<b>ожидают публикации:</b> {total_sched}"
    )
    lines.append("")
    lines.append(
        blockquote(
            "Свободно — тексты, которые пользователи могут взять сейчас. "
            "Когда остаток падает — добавляйте новые тексты в пул."
        )
    )
    return "\n".join(lines)


async def send_reviews_stock_to_admins(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings | None = None,
) -> tuple[int, int]:
    """Отправить отчёт всем ADMIN_IDS. Возвращает (успех, ошибки)."""
    settings = settings or get_settings()
    if not settings.admin_ids:
        logger.warning("REVIEWS_STOCK: ADMIN_IDS пуст — некому отправлять")
        return 0, 0
    async with session_factory() as session:
        rows = await fetch_platform_review_stock(session)
    text = build_reviews_stock_message(rows, settings)
    ok = bad = 0
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            bad += 1
        except Exception:
            logger.exception("REVIEWS_STOCK: не отправлено admin_id=%s", admin_id)
            bad += 1
    return ok, bad


def seconds_until_daily_report(
    tz_name: str,
    *,
    hour: int = 22,
    minute: int = 0,
) -> float:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    target = datetime.combine(now.date(), time(hour, minute), tzinfo=tz)
    if now >= target:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


async def reviews_stock_scheduler_loop(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Каждый день в заданное время (по APP_TIMEZONE) — отчёт админам."""
    while True:
        settings = get_settings()
        wait = seconds_until_daily_report(
            settings.app_timezone,
            hour=settings.reviews_stock_report_hour,
            minute=settings.reviews_stock_report_minute,
        )
        logger.info(
            "Следующий отчёт по отзывам через %.0f с (%02d:%02d %s)",
            wait,
            settings.reviews_stock_report_hour,
            settings.reviews_stock_report_minute,
            settings.app_timezone,
        )
        try:
            await asyncio.sleep(wait)
            ok, bad = await send_reviews_stock_to_admins(bot, session_factory, settings)
            logger.info("Ежедневный отчёт по отзывам: ok=%s bad=%s", ok, bad)
            await asyncio.sleep(90)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка планировщика отчёта по отзывам")
            await asyncio.sleep(60)
