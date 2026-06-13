from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.admin.states import AdminApprovedExportFSM
from handlers.formatting import blockquote, section_rich
from handlers.keyboards import (
    A_APPROVED_REVIEWS,
    BTN_APPROVED_EXPORT_30,
    BTN_APPROVED_EXPORT_7,
    BTN_APPROVED_EXPORT_RANGE,
    admin_approved_reviews_kb,
    admin_cancel_kb,
)
from services.approved_reviews import (
    approved_stats_text,
    build_approved_reviews_xlsx,
    list_approved_reviews,
    parse_admin_date,
    utc_now_in_tz,
    fetch_approved_review_stats,
)

router = Router(name="admin_approved_reviews")


async def _send_export(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    date_from,
    date_to,
    label: str,
) -> None:
    async with session_factory() as session:
        rows = await list_approved_reviews(
            session,
            date_from=date_from,
            date_to=date_to,
            tz_name=settings.app_timezone,
        )
    if not rows:
        await message.answer(
            f"За период «{label}» подтверждённых отзывов нет.",
            reply_markup=admin_approved_reviews_kb(),
        )
        return
    xlsx = build_approved_reviews_xlsx(rows, tz_name=settings.app_timezone)
    fname = f"approved_reviews_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.xlsx"
    await message.answer_document(
        BufferedInputFile(xlsx, filename=fname),
        caption=f"✅ {label}: {len(rows)} отзыв(ов)",
        reply_markup=admin_approved_reviews_kb(),
    )


@router.message(F.text == A_APPROVED_REVIEWS)
async def msg_approved_reviews_root(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    async with session_factory() as session:
        stats = await fetch_approved_review_stats(session, tz_name=settings.app_timezone)
        recent = await list_approved_reviews(
            session, tz_name=settings.app_timezone, limit=5
        )
    extra = ""
    if recent:
        lines = []
        for row in recent:
            dt = row.approved_at.strftime("%d.%m.%Y") if row.approved_at else "—"
            lines.append(f"· #{row.id} {dt} — {row.city}, {row.gender}")
        extra = f"\n\n<b>Последние 5:</b>\n" + "\n".join(lines)
    await message.answer(
        f"✅ <b>Подтверждённые отзывы</b>\n\n"
        f"{section_rich('Статистика', approved_stats_text(stats))}"
        f"{extra}\n\n"
        f"{blockquote('Выгрузка Excel: дата, город, пол, текст, ссылка.')}",
        parse_mode="HTML",
        reply_markup=admin_approved_reviews_kb(),
    )


@router.message(F.text == BTN_APPROVED_EXPORT_7)
async def msg_approved_export_7(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    today = utc_now_in_tz(settings.app_timezone).date()
    date_from = today - timedelta(days=6)
    await _send_export(
        message,
        session_factory,
        settings,
        date_from=date_from,
        date_to=today,
        label="7 дней",
    )


@router.message(F.text == BTN_APPROVED_EXPORT_30)
async def msg_approved_export_30(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    today = utc_now_in_tz(settings.app_timezone).date()
    date_from = today - timedelta(days=29)
    await _send_export(
        message,
        session_factory,
        settings,
        date_from=date_from,
        date_to=today,
        label="30 дней",
    )


@router.message(F.text == BTN_APPROVED_EXPORT_RANGE)
async def msg_approved_export_range_start(
    message: Message,
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(AdminApprovedExportFSM.date_from)
    await message.answer(
        f"📅 <b>Выгрузка Excel</b>\n\n"
        f"{blockquote('Введите дату начала периода, например 01.03.2026')}",
        parse_mode="HTML",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminApprovedExportFSM.date_from, F.text)
async def msg_approved_export_date_from(
    message: Message,
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    d = parse_admin_date(message.text or "")
    if not d:
        await message.answer(
            "Неверная дата. Формат: ДД.ММ.ГГГГ",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.update_data(export_date_from=d.isoformat())
    await state.set_state(AdminApprovedExportFSM.date_to)
    await message.answer(
        f"Дата начала: <b>{d.strftime('%d.%m.%Y')}</b>\n\n"
        f"Введите дату окончания периода:",
        parse_mode="HTML",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminApprovedExportFSM.date_to, F.text)
async def msg_approved_export_date_to(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    d_to = parse_admin_date(message.text or "")
    if not d_to:
        await message.answer(
            "Неверная дата. Формат: ДД.ММ.ГГГГ",
            reply_markup=admin_cancel_kb(),
        )
        return
    data = await state.get_data()
    raw_from = data.get("export_date_from")
    d_from = date.fromisoformat(raw_from) if raw_from else d_to
    await state.clear()
    label = f"{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}"
    await _send_export(
        message,
        session_factory,
        settings,
        date_from=d_from,
        date_to=d_to,
        label=label,
    )
