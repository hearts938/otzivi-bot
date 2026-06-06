from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import Platform, SubmissionStatus, TaskText
from handlers.filters import OnboardingCompletedFilter
from handlers.formatting import (
    assignment_message,
    blockquote,
    profile_text,
    referral_text,
    section,
    platform_tasks_header,
    tasks_menu_entry_text,
)
from handlers.keyboards import (
    BTN_BACK_MENU,
    BTN_BACK_PLATFORMS,
    BTN_PROFILE,
    BTN_REFERRAL,
    BTN_WITHDRAW,
    BTN_TASK_DONE,
    BTN_TASK_REFUSE,
    BTN_TASKS,
    BTN_BACK_TASKS,
    parse_task_pick,
    parse_user_platform_pick,
    task_pick_label,
    user_back_menu_kb,
    user_main_kb,
    user_platform_pick_label,
    user_platforms_kb,
    user_profile_kb,
    user_task_actions_kb,
    user_tasks_kb,
)
from config import Settings, get_settings
from handlers.menu_common import return_to_main_menu
from repo import (
    claim_min_available_text,
    create_submission,
    ensure_user,
    get_submission_for_user_task,
    get_task,
    get_user_by_telegram,
    get_user_claimed_text,
    user_refused_text,
    list_platforms_available_for_user,
    list_tasks_available_for_user,
    list_tasks_available_for_user_on_platform,
    count_approved_submissions,
    count_referred_users,
    create_withdrawal_and_debit,
    release_expired_task_claims,
    release_task_text,
    touch_activity,
    list_user_withdrawals,
    update_withdrawal_request_status,
    reset_incomplete_ym_flow,
)
from handlers.admin.common import is_admin
from repo import user_is_banned_now
from services.yandex_maps import is_yandex_maps_slug
from services.payments_api import create_fps_payment

router = Router(name="user")
router.message.filter(OnboardingCompletedFilter())


class UserGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session_factory: async_sessionmaker[AsyncSession] | None = data.get("session_factory")
        if session_factory is None:
            return await handler(event, data)
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)
        uid = event.from_user.id
        async with session_factory() as session:
            u = await get_user_by_telegram(session, uid)
            if u and user_is_banned_now(u):
                await event.answer("Аккаунт заблокирован.")
                return
            if u:
                await touch_activity(session, u.id)
        return await handler(event, data)


router.message.middleware(UserGateMiddleware())


class WithdrawFSM(StatesGroup):
    amount = State()
    fps_phone = State()
    fps_bank_id = State()


@router.message(F.text == BTN_BACK_MENU)
@router.message(F.text == "/menu")
async def msg_menu(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    await return_to_main_menu(message, state, session_factory, settings)


async def _send_platform_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
) -> None:
    await state.clear()
    settings = get_settings()
    async with session_factory() as session:
        await release_expired_task_claims(session, settings.task_claim_minutes)
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        await reset_incomplete_ym_flow(session, u.id)
        rows = await list_platforms_available_for_user(session, u.id, u.gender)
    if not rows:
        await message.answer(
            "Сейчас нет доступных заданий для вас: нет свободных отзывов под ваш пол "
            "или вы уже отправили отзыв по всем актуальным заданиям.",
            reply_markup=user_main_kb(),
        )
        return
    labels = [user_platform_pick_label(p.id, p.name, cnt) for p, cnt in rows]
    await message.answer(
        tasks_menu_entry_text(len(rows), claim_minutes=settings.task_claim_minutes),
        reply_markup=user_platforms_kb(labels),
        parse_mode="HTML",
    )


async def _send_customer_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    platform_id: int,
) -> None:
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        p = await session.get(Platform, platform_id)
        if not p or not p.active:
            await state.clear()
            await message.answer("Сервис недоступен.", reply_markup=user_main_kb())
            return
        tasks = await list_tasks_available_for_user_on_platform(
            session, u.id, u.gender, platform_id
        )
    if not tasks:
        await message.answer("По этому сервису сейчас нет доступных заказчиков.")
        await _send_platform_list(message, session_factory, state)
        return
    await state.update_data(tasks_platform_id=platform_id)
    labels = [
        task_pick_label(t.id, t.customer_name or t.title or "", t.reward or 0)
        for t in tasks
    ]
    await message.answer(
        platform_tasks_header(p.name, len(tasks)),
        reply_markup=user_tasks_kb(labels),
        parse_mode="HTML",
    )


@router.message(F.text == BTN_TASKS)
@router.message(F.text == BTN_BACK_PLATFORMS)
async def msg_tasks(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    await _send_platform_list(message, session_factory, state)


@router.message(F.text == BTN_BACK_TASKS)
async def msg_back_to_customers(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    data = await state.get_data()
    pid = data.get("tasks_platform_id")
    if pid:
        await _send_customer_list(message, session_factory, state, int(pid))
        return
    await _send_platform_list(message, session_factory, state)


@router.message(F.text.func(lambda t: parse_user_platform_pick(t) is not None))
async def msg_platform_pick(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    pid = parse_user_platform_pick(message.text or "")
    if pid is None:
        return
    async with session_factory() as session:
        p = await session.get(Platform, pid)
        if p and is_yandex_maps_slug(p.slug):
            return
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        await reset_incomplete_ym_flow(session, u.id)
    await state.clear()
    await _send_customer_list(message, session_factory, state, pid)


@router.message(F.text.func(lambda t: parse_task_pick(t) is not None))
async def msg_task_open(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    tid = parse_task_pick(message.text or "")
    if tid is None:
        return
    settings = get_settings()
    async with session_factory() as session:
        await release_expired_task_claims(session, settings.task_claim_minutes)
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        t = await get_task(session, tid)
        if not t or not t.active:
            await message.answer("Задание недоступно.", reply_markup=user_main_kb())
            return
        sub = await get_submission_for_user_task(session, u.id, tid)
        if sub:
            await message.answer(
                "Вы уже выполняли задание этого заказчика. "
                "Повторно взять его нельзя.",
                reply_markup=user_main_kb(),
            )
            return
        claimed = await get_user_claimed_text(session, u.id, tid)
        if claimed and await user_refused_text(session, u.id, claimed.id):
            tt_fix = await session.get(TaskText, claimed.id)
            if tt_fix and tt_fix.taken_by_user_id == u.id:
                tt_fix.taken_by_user_id = None
                tt_fix.claimed_at = None
                await session.commit()
            claimed = None
        if claimed:
            await state.update_data(tasks_platform_id=t.platform_id)
            await _show_assignment(message, t, claimed, settings)
            return
        visible = await list_tasks_available_for_user_on_platform(
            session, u.id, u.gender, t.platform_id
        )
        if not any(x.id == tid for x in visible):
            await message.answer("Это задание сейчас недоступно.", reply_markup=user_main_kb())
            return
        claimed = await claim_min_available_text(session, u.id, tid, u.gender)
    await state.update_data(tasks_platform_id=t.platform_id)
    if not claimed:
        await message.answer(
            "Не удалось взять задание: свободных текстов нет или их уже заняли.",
            reply_markup=user_main_kb(),
        )
        return
    await _show_assignment(message, t, claimed, settings)


async def _show_assignment(message: Message, task, claimed, settings: Settings) -> None:
    await message.answer(
        assignment_message(task, claimed, claim_minutes=settings.task_claim_minutes),
        reply_markup=user_task_actions_kb(),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


@router.message(F.text == BTN_TASK_REFUSE)
async def msg_refuse(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    settings = get_settings()
    async with session_factory() as session:
        await release_expired_task_claims(session, settings.task_claim_minutes)
        u = await ensure_user(session, message.from_user.id, message.from_user.username, referred_by_id=None)
        from repo import list_active_tasks

        released = False
        for t in await list_active_tasks(session):
            claimed = await get_user_claimed_text(session, u.id, t.id)
            if not claimed:
                continue
            sub = await get_submission_for_user_task(session, u.id, t.id)
            if sub:
                await message.answer(
                    "Нельзя отменить задание: отзыв уже отправлен на проверку.",
                    reply_markup=user_task_actions_kb(),
                )
                return
            if await release_task_text(session, u.id, claimed.id):
                released = True
            break
    if not released:
        await message.answer("Нет активного задания для отказа.", reply_markup=user_main_kb())
        return
    data = await state.get_data()
    pid = data.get("tasks_platform_id")
    await message.answer(
        "Вы отказались от задания. Этот текст Вы больше не сможете взять. "
        "Вы можете взять другое задание.",
        reply_markup=user_main_kb(),
    )
    if pid:
        await _send_customer_list(message, session_factory, state, int(pid))
    else:
        await _send_platform_list(message, session_factory, state)


@router.message(F.text == BTN_TASK_DONE)
async def msg_done(message: Message, session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        u = await ensure_user(session, message.from_user.id, message.from_user.username, referred_by_id=None)
        from repo import list_active_tasks

        tid, claimed = None, None
        for t in await list_active_tasks(session):
            c = await get_user_claimed_text(session, u.id, t.id)
            if c:
                tid, claimed = t.id, c
                break
        if not tid or not claimed:
            await message.answer("Сначала возьмите задание в разделе «Задания».", reply_markup=user_main_kb())
            return
        sub = await create_submission(session, u.id, tid, claimed.body, task_text_id=claimed.id)
    if not sub:
        await message.answer("Уже отправлено на проверку.", reply_markup=user_main_kb())
        return
    if sub.status == SubmissionStatus.COOLDOWN and sub.cooldown_until:
        await message.answer(
            f"✅ <b>Отмечено как выполненное</b>\n\n"
            f"{section('Кулдаун сервиса', 'После окончания кулдауна задание появится у администратора на проверке.')}",
            parse_mode="HTML",
            reply_markup=user_main_kb(),
        )
    else:
        await message.answer(
            f"✅ <b>Отправлено на проверку</b>\n\n"
            f"{blockquote('Администратор проверит отзыв в разделе «Задания на проверке».')}",
            parse_mode="HTML",
            reply_markup=user_main_kb(),
        )


async def _send_profile(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        ref_n = await count_referred_users(session, u.id)
        done = await count_approved_submissions(session, u.id)
    await message.answer(
        profile_text(
            u,
            referred_count=ref_n,
            completed_tasks=done,
            reviews_channel_url=settings.reviews_channel_url,
            percent_up_to=settings.referral_percent_up_to_threshold,
            percent_after=settings.referral_percent_after_threshold,
            count_threshold=settings.referral_count_threshold,
        ),
        parse_mode="HTML",
        reply_markup=user_profile_kb(),
    )


@router.message(F.text == BTN_PROFILE)
async def msg_profile(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    await state.clear()
    await _send_profile(message, session_factory, settings)


@router.message(F.text == BTN_WITHDRAW)
async def msg_withdraw_start(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        recent = await list_user_withdrawals(session, u.id, limit=3)
    if not settings.payments_api_auth:
        await message.answer(
            "Вывод временно недоступен: не настроен API оплаты.",
            reply_markup=user_profile_kb(),
        )
        return
    if float(u.balance or 0) <= 0:
        await message.answer(
            "Недостаточно средств на балансе к выплате.",
            reply_markup=user_profile_kb(),
        )
        return
    hist = ""
    if recent:
        lines = []
        for w in recent:
            pid = w.external_payment_id or "—"
            lines.append(f"· {w.amount:.2f} ₽ — {w.status} (id {pid})")
        hist = "\n\nПоследние выплаты:\n" + "\n".join(lines)
    await state.set_state(WithdrawFSM.amount)
    await message.answer(
        f"💸 <b>Вывод средств</b>\n\n"
        f"Доступно к выплате: <b>{float(u.balance or 0):.2f} ₽</b>\n\n"
        f"{blockquote('Введите сумму вывода в рублях, например 500 или 1250.50.')}"
        f"{hist}",
        parse_mode="HTML",
        reply_markup=user_back_menu_kb(),
    )


@router.message(WithdrawFSM.amount, F.text)
async def msg_withdraw_amount(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    raw = (message.text or "").strip().replace(",", ".")
    if raw.startswith("+"):
        raw = raw[1:].strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите сумму числом.", reply_markup=user_back_menu_kb())
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.", reply_markup=user_back_menu_kb())
        return
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
    if amount > float(u.balance or 0):
        await message.answer(
            f"Недостаточно средств. Доступно: {float(u.balance or 0):.2f} ₽",
            reply_markup=user_back_menu_kb(),
        )
        return
    await state.update_data(withdraw_amount=round(amount, 2))
    await state.set_state(WithdrawFSM.fps_phone)
    await message.answer(
        "Введите номер телефона для СБП (например <code>+79991234567</code>).",
        parse_mode="HTML",
        reply_markup=user_back_menu_kb(),
    )


@router.message(WithdrawFSM.fps_phone, F.text)
async def msg_withdraw_fps_phone(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(" ", "")
    phone = raw
    if phone.startswith("8") and len(phone) == 11:
        phone = "+7" + phone[1:]
    if not phone.startswith("+") and phone.isdigit():
        phone = "+" + phone
    if len(phone) < 11 or len(phone) > 16 or not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer(
            "Неверный формат телефона. Пример: <code>+79991234567</code>",
            parse_mode="HTML",
            reply_markup=user_back_menu_kb(),
        )
        return
    await state.update_data(withdraw_fps_phone=phone)
    await state.set_state(WithdrawFSM.fps_bank_id)
    await message.answer(
        "Введите <b>fps_bank_member_id</b> банка (из справочника API).",
        parse_mode="HTML",
        reply_markup=user_back_menu_kb(),
    )


@router.message(WithdrawFSM.fps_bank_id, F.text)
async def msg_withdraw_fps_bank(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    bank_id = (message.text or "").strip()
    if len(bank_id) < 3:
        await message.answer("Введите корректный fps_bank_member_id.", reply_markup=user_back_menu_kb())
        return
    data = await state.get_data()
    amount = float(data.get("withdraw_amount") or 0)
    phone = str(data.get("withdraw_fps_phone") or "")
    if amount <= 0 or not phone:
        await state.clear()
        await message.answer("Сессия вывода сброшена. Начните снова.", reply_markup=user_profile_kb())
        return
    await message.answer("Создаю заявку и списываю баланс, подождите...")
    request_id: int | None = None
    new_balance: float = 0.0
    tg_id: int = 0
    first_name: str | None = None
    last_name: str | None = None
    async with session_factory() as session:
        u_db = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        created = await create_withdrawal_and_debit(
            session,
            user_id=u_db.id,
            amount=amount,
            fps_phone=phone,
            fps_bank_member_id=bank_id,
        )
        if created is None:
            await state.clear()
            await message.answer(
                "Недостаточно средств на балансе к выплате.",
                reply_markup=user_profile_kb(),
            )
            return
        wr_db, debited_user = created
        request_id = wr_db.id
        new_balance = float(debited_user.balance or 0)
        tg_id = int(debited_user.telegram_id)
        first_name = debited_user.first_name
        last_name = debited_user.last_name
    result = await asyncio.to_thread(
        create_fps_payment,
        settings,
        amount=amount,
        service_title="Вывод средств",
        purpose=f"Вывод средств пользователю {tg_id}",
        fps_mobile_phone=phone,
        fps_bank_member_id=bank_id,
        first_name=first_name,
        last_name=last_name,
        patronymic=None,
    )
    wr = None
    async with session_factory() as session:
        wr = await update_withdrawal_request_status(
            session,
            int(request_id or 0),
            status=result.status,
            external_payment_id=result.payment_id,
            error_message=result.error_message,
        )
    await state.clear()
    if result.ok:
        await message.answer(
            f"✅ Выплата создана.\n"
            f"ID платежа: <code>{result.payment_id or '—'}</code>\n"
            f"Статус: <b>{result.status}</b>\n"
            f"Новый баланс: <b>{new_balance:.2f} ₽</b>",
            parse_mode="HTML",
            reply_markup=user_profile_kb(),
        )
        return
    await message.answer(
        f"❌ Не удалось выполнить вывод.\n"
        f"Статус: <b>{result.status}</b>\n"
        f"Ошибка: <code>{(result.error_message or 'неизвестно')[:350]}</code>\n"
        f"Номер заявки: <code>{wr.id if wr else request_id or '—'}</code>",
        parse_mode="HTML",
        reply_markup=user_profile_kb(),
    )


@router.message(F.text == BTN_REFERRAL)
async def msg_referral(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        ref_n = await count_referred_users(session, u.id)
    me = await message.bot.get_me()
    un = me.username or "bot"
    link = f"https://t.me/{un}?start=ref_{u.referral_code}"
    await message.answer(
        referral_text(
            u,
            link,
            ref_n,
            percent_up_to=settings.referral_percent_up_to_threshold,
            percent_after=settings.referral_percent_after_threshold,
            count_threshold=settings.referral_count_threshold,
        ),
        parse_mode="HTML",
        reply_markup=user_main_kb(is_admin=is_admin(message.from_user.id, settings)),
    )
