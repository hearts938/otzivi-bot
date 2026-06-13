from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import Submission, SubmissionStatus, User
from handlers.admin.common import is_admin
from handlers.formatting import admin_submission_review_text, blockquote
from handlers.keyboards import (
    A_REVIEW,
    BTN_ADMIN_HOME,
    BTN_BACK_REVIEW,
    admin_back_home_kb,
    admin_labeled_list_kb,
    admin_moderation_item_kb,
    _kb,
    _rows,
    parse_review_platform,
    parse_review_task,
    parse_submission_action,
    review_platform_label,
)
from repo import (
    count_submissions_in_cooldown,
    get_submission_detail,
    list_pending_submissions_for_platform,
    list_platforms_with_pending_reviews,
)
from services.rewards import approve_submission, reject_submission

router = Router(name="admin_review")


def _review_queue_hint(pending: int, waiting_cooldown: int) -> str:
    return (
        f"На проверке: <b>{pending}</b>\n"
        f"Ожидается (кулдаун): <b>{waiting_cooldown}</b>"
    )


async def _send_platform_reviews(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    platform_id: int,
) -> None:
    async with session_factory() as session:
        subs = await list_pending_submissions_for_platform(session, platform_id)
        waiting = await count_submissions_in_cooldown(session, platform_id=platform_id)
    hint = _review_queue_hint(len(subs), waiting)
    if not subs:
        await message.answer(
            f"📋 <b>Задания на проверке</b>\n\n{blockquote(hint if waiting else 'Нет отзывов на проверке по этому сервису.')}",
            parse_mode="HTML",
            reply_markup=admin_labeled_list_kb([], [BTN_BACK_REVIEW, BTN_ADMIN_HOME]),
        )
        return
    await message.answer(
        f"📋 <b>Задания на проверке</b>\n\n{blockquote(hint)}",
        parse_mode="HTML",
        reply_markup=_kb(_rows(BTN_BACK_REVIEW, BTN_ADMIN_HOME)),
    )
    for sub in subs:
        task = sub.task
        await message.answer(
            admin_submission_review_text(sub, task),
            parse_mode="HTML",
            reply_markup=admin_moderation_item_kb(sub.id),
        )


@router.message(F.text == A_REVIEW)
@router.message(F.text == BTN_BACK_REVIEW)
async def msg_review_root(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    async with session_factory() as session:
        rows = await list_platforms_with_pending_reviews(session)
        waiting = await count_submissions_in_cooldown(session)
    pending_total = sum(cnt for _, cnt in rows)
    hint = _review_queue_hint(pending_total, waiting)
    if not rows:
        await message.answer(
            f"📋 <b>Задания на проверке</b>\n\n{blockquote(hint if waiting else 'Сейчас нет отзывов, ожидающих проверки.')}",
            parse_mode="HTML",
            reply_markup=admin_back_home_kb(),
        )
        return
    labels = [review_platform_label(p.id, p.name, cnt) for p, cnt in rows]
    await message.answer(
        f"📋 <b>Задания на проверке</b>\n\n{blockquote(hint)}\n\nВыберите сервис.",
        parse_mode="HTML",
        reply_markup=admin_labeled_list_kb(labels, [BTN_BACK_REVIEW, BTN_ADMIN_HOME]),
    )


@router.message(F.text.func(lambda t: parse_review_platform(t) is not None))
async def msg_review_platform(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_review_platform(message.text or "")
    if pid is None:
        return
    await state.update_data(review_platform_id=pid)
    await _send_platform_reviews(message, session_factory, pid)


@router.message(F.text.func(lambda t: parse_review_task(t) is not None))
async def msg_review_task_legacy(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    data = await state.get_data()
    pid = data.get("review_platform_id")
    if not pid:
        await msg_review_root(message, session_factory, settings, state)
        return
    await _send_platform_reviews(message, session_factory, int(pid))


@router.message(F.text.func(lambda t: parse_submission_action(t) is not None))
async def msg_review_action(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    parsed = parse_submission_action(message.text or "")
    if not parsed:
        return
    action, sid = parsed
    if action == "ok":
        async with session_factory() as session:
            info = await approve_submission(session, settings, sid)
        if not info:
            await message.answer("Не удалось одобрить.", reply_markup=admin_back_home_kb())
            return
        await message.answer(info, reply_markup=admin_back_home_kb())
        async with session_factory() as session:
            sub = await session.get(Submission, sid)
            if sub and sub.status == SubmissionStatus.APPROVED:
                u = await session.get(User, sub.user_id)
                if u:
                    try:
                        await message.bot.send_message(
                            u.telegram_id,
                            "✅ Отзыв одобрен, вознаграждение на балансе.",
                        )
                    except (TelegramForbiddenError, TelegramBadRequest):
                        pass
        return
    async with session_factory() as session:
        ok = await reject_submission(session, sid)
        sub = await get_submission_detail(session, sid)
    if not ok:
        await message.answer("Не удалось отклонить.", reply_markup=admin_back_home_kb())
        return
    await message.answer("Отклонено.", reply_markup=admin_back_home_kb())
    if sub and sub.status == SubmissionStatus.REJECTED and sub.user:
        try:
            await message.bot.send_message(sub.user.telegram_id, "Отзыв не принят модератором.")
        except (TelegramForbiddenError, TelegramBadRequest):
            pass
