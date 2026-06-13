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
    BTN_APPROVED_ALL_PLATFORMS,
    BTN_APPROVED_ALL_TASKS,
    BTN_APPROVED_EXPORT_30,
    BTN_APPROVED_EXPORT_7,
    BTN_APPROVED_EXPORT_RANGE,
    admin_approved_reviews_kb,
    admin_cancel_kb,
    admin_labeled_list_kb,
    approved_platform_label,
    approved_task_label,
    parse_approved_platform,
    parse_approved_task,
)
from services.approved_reviews import (
    approved_stats_text,
    build_approved_reviews_xlsx,
    fetch_approved_review_stats,
    list_approved_review_platforms,
    list_approved_review_tasks,
    list_approved_reviews,
    parse_admin_date,
    utc_now_in_tz,
)

router = Router(name="admin_approved_reviews")


async def _send_export(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    date_from: date,
    date_to: date,
    label: str,
    platform_id: int | None = None,
    task_id: int | None = None,
) -> None:
    async with session_factory() as session:
        rows = await list_approved_reviews(
            session,
            date_from=date_from,
            date_to=date_to,
            platform_id=platform_id,
            task_id=task_id,
            tz_name=settings.app_timezone,
        )
    if not rows:
        await message.answer(
            f"За период «{label}» подтверждённых отзывов нет.",
            reply_markup=admin_approved_reviews_kb(),
        )
        return
    xlsx = build_approved_reviews_xlsx(rows, tz_name=settings.app_timezone)
    fname = f"approved_reviews_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}"
    if platform_id is not None:
        fname += f"_pf{platform_id}"
    if task_id is not None:
        fname += f"_tk{task_id}"
    fname += ".xlsx"
    await message.answer_document(
        BufferedInputFile(xlsx, filename=fname),
        caption=f"✅ {label}: {len(rows)} отзыв(ов)",
        reply_markup=admin_approved_reviews_kb(),
    )


async def _ask_export_platform(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
) -> None:
    async with session_factory() as session:
        rows = await list_approved_review_platforms(session)
    labels = [approved_platform_label(p.id, p.name, cnt) for p, cnt in rows]
    await state.set_state(AdminApprovedExportFSM.platform_pick)
    await message.answer(
        f"🌐 <b>Сервис</b>\n\n"
        f"{blockquote('Выберите сервис или «Все сервисы».')}",
        parse_mode="HTML",
        reply_markup=admin_labeled_list_kb(
            [BTN_APPROVED_ALL_PLATFORMS, *labels],
            [A_APPROVED_REVIEWS],
        ),
    )


async def _ask_export_task(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    *,
    platform_id: int | None,
) -> None:
    async with session_factory() as session:
        rows = await list_approved_review_tasks(session, platform_id=platform_id)
    labels = [
        approved_task_label(
            t.id,
            (t.customer_name or t.title or "").strip() or f"#{t.id}",
            cnt,
        )
        for t, cnt in rows
    ]
    await state.set_state(AdminApprovedExportFSM.task_pick)
    scope = "по выбранному сервису" if platform_id is not None else "по всем сервисам"
    await message.answer(
        f"📋 <b>Заказчик</b>\n\n"
        f"{blockquote(f'Выберите заказчика ({scope}) или «Все заказчики».')}",
        parse_mode="HTML",
        reply_markup=admin_labeled_list_kb(
            [BTN_APPROVED_ALL_TASKS, *labels],
            [A_APPROVED_REVIEWS],
        ),
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
        f"{blockquote('Выгрузка Excel: дата, город, пол, текст, ссылка. Можно фильтровать по сервису и заказчику.')}",
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
    today = utc_now_in_tz(settings.app_timezone).date()
    date_from = today - timedelta(days=6)
    await state.update_data(
        export_date_from=date_from.isoformat(),
        export_date_to=today.isoformat(),
        export_label="7 дней",
    )
    await _ask_export_platform(message, session_factory, state)


@router.message(F.text == BTN_APPROVED_EXPORT_30)
async def msg_approved_export_30(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    today = utc_now_in_tz(settings.app_timezone).date()
    date_from = today - timedelta(days=29)
    await state.update_data(
        export_date_from=date_from.isoformat(),
        export_date_to=today.isoformat(),
        export_label="30 дней",
    )
    await _ask_export_platform(message, session_factory, state)


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
    label = f"{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}"
    await state.update_data(
        export_date_from=d_from.isoformat(),
        export_date_to=d_to.isoformat(),
        export_label=label,
    )
    await _ask_export_platform(message, session_factory, state)


@router.message(AdminApprovedExportFSM.platform_pick, F.text)
async def msg_approved_export_platform_pick(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    text = (message.text or "").strip()
    if text == A_APPROVED_REVIEWS:
        await state.clear()
        await msg_approved_reviews_root(message, session_factory, settings, state)
        return
    platform_id: int | None
    if text == BTN_APPROVED_ALL_PLATFORMS:
        platform_id = None
    else:
        platform_id = parse_approved_platform(text)
        if platform_id is None:
            await message.answer(
                "Выберите сервис из списка.",
                reply_markup=admin_cancel_kb(),
            )
            return
    await state.update_data(export_platform_id=platform_id)
    await _ask_export_task(message, session_factory, state, platform_id=platform_id)


@router.message(AdminApprovedExportFSM.task_pick, F.text)
async def msg_approved_export_task_pick(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    text = (message.text or "").strip()
    if text == A_APPROVED_REVIEWS:
        await state.clear()
        await msg_approved_reviews_root(message, session_factory, settings, state)
        return
    task_id: int | None
    if text == BTN_APPROVED_ALL_TASKS:
        task_id = None
    else:
        task_id = parse_approved_task(text)
        if task_id is None:
            await message.answer(
                "Выберите заказчика из списка.",
                reply_markup=admin_cancel_kb(),
            )
            return
    data = await state.get_data()
    raw_from = data.get("export_date_from")
    raw_to = data.get("export_date_to")
    if not raw_from or not raw_to:
        await state.clear()
        await message.answer(
            "Сессия выгрузки сброшена. Начните снова.",
            reply_markup=admin_approved_reviews_kb(),
        )
        return
    d_from = date.fromisoformat(raw_from)
    d_to = date.fromisoformat(raw_to)
    label = data.get("export_label") or f"{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}"
    platform_id = data.get("export_platform_id")
    if platform_id is not None:
        platform_id = int(platform_id)
    await state.clear()
    await _send_export(
        message,
        session_factory,
        settings,
        date_from=d_from,
        date_to=d_to,
        label=label,
        platform_id=platform_id,
        task_id=task_id,
    )
