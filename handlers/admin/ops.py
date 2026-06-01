from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.formatting import blockquote, section
from handlers.keyboards import (
    A_BALANCE,
    BTN_BALANCE_CREDIT,
    BTN_BALANCE_DEBIT,
    A_OUTREACH,
    A_PF_ADD,
    A_PF_CD,
    A_PF_DEL,
    A_STARS,
    BTN_ADMIN_HOME,
    admin_back_home_kb,
    admin_balance_action_kb,
    admin_cancel_kb,
    admin_labeled_list_kb,
    cooldown_platform_label,
    delete_platform_label,
    parse_cooldown_platform,
    parse_delete_platform,
    platform_pick_label,
)
from handlers.admin.states import BalanceFSM, OutreachFSM, PlatformAddFSM, PlatformCdFSM, StarsFSM
from services.cooldown_input import (
    COOLDOWN_HOURS_INVALID,
    COOLDOWN_HOURS_PROMPT,
    format_cooldown_hours,
    hours_to_cooldown_seconds,
    parse_cooldown_hours,
)
from repo import (
    apply_user_balance_change,
    create_platform,
    delete_platform,
    get_default_platform,
    get_setting,
    list_platforms_all,
    resolve_user_ref,
    set_setting,
    update_platform_cooldown,
)

router = Router(name="admin_ops")


@router.message(F.text == A_BALANCE)
async def bal_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(BalanceFSM.user_ref)
    await message.answer(
        f"💳 <b>Баланс</b>\n\n{blockquote('Укажите @username или числовой Telegram ID.')}",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


def _balance_user_card(u) -> str:
    un = f"@{u.username}" if u.username else "—"
    pending = float(u.pending_balance or 0)
    return (
        f"Username: <b>{un}</b>\n"
        f"Telegram ID: <code>{u.telegram_id}</code>\n"
        f"ID в базе: <code>{u.id}</code>\n"
        f"Баланс к выплате: <b>{u.balance:.2f}</b> ₽\n"
        f"В ожидании: <b>{pending:.2f}</b> ₽"
    )


@router.message(BalanceFSM.user_ref, F.text)
async def bal_user(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    ref = (message.text or "").strip()
    async with session_factory() as session:
        u = await resolve_user_ref(session, ref)
    if not u:
        await message.answer(
            "Пользователь не найден. Укажите @username или числовой Telegram ID.",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.update_data(balance_user_id=u.id)
    await state.set_state(BalanceFSM.action)
    await message.answer(
        f"💳 <b>Баланс пользователя</b>\n\n"
        f"{section('Данные', _balance_user_card(u))}\n\n"
        f"{blockquote('Выберите: начислить или списать с баланса к выплате.')}",
        parse_mode="HTML",
        reply_markup=admin_balance_action_kb(),
    )


@router.message(BalanceFSM.action, F.text.in_({BTN_BALANCE_CREDIT, BTN_BALANCE_DEBIT}))
async def bal_action(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    credit = message.text == BTN_BALANCE_CREDIT
    await state.update_data(balance_credit=credit)
    await state.set_state(BalanceFSM.amount)
    verb = "начисления" if credit else "списания"
    await message.answer(
        f"Введите сумму для {verb} (₽), только положительное число:",
        reply_markup=admin_cancel_kb(),
    )


@router.message(BalanceFSM.action)
async def bal_action_invalid(message: Message, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        return
    await message.answer(
        "Выберите «Начислить» или «Списать».",
        reply_markup=admin_balance_action_kb(),
    )


@router.message(BalanceFSM.amount, F.text)
async def bal_amt(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    user_id = data.get("balance_user_id")
    credit = data.get("balance_credit")
    if user_id is None or credit is None:
        await state.clear()
        await message.answer("Сессия сброшена. Начните с «Баланс».", reply_markup=admin_back_home_kb())
        return
    raw = (message.text or "").strip().replace(",", ".").replace("−", "-").replace("–", "-")
    if raw.startswith("+"):
        raw = raw[1:].strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Нужно число, например 100 или 250.50", reply_markup=admin_cancel_kb())
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.", reply_markup=admin_cancel_kb())
        return
    await state.clear()
    async with session_factory() as session:
        u2 = await apply_user_balance_change(
            session, int(user_id), amount, credit=bool(credit)
        )
    if not u2:
        await message.answer("Пользователь не найден.", reply_markup=admin_back_home_kb())
        return
    op = "Начислено" if credit else "Списано"
    await message.answer(
        f"✅ <b>{op} {amount:.2f} ₽</b>\n\n"
        f"{section('Пользователь', _balance_user_card(u2))}",
        parse_mode="HTML",
        reply_markup=admin_back_home_kb(),
    )


@router.message(F.text == A_STARS)
async def str_start(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        cur = await get_setting(session, "stars_rub_per_star", "1.0")
    await state.set_state(StarsFSM.rate)
    await message.answer(
        f"⭐ Курс: 1★ = {cur} ₽\n\n{blockquote('Введите новое значение (руб/звезда).')}",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(StarsFSM.rate, F.text)
async def str_rate(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    try:
        v = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Нужно число.", reply_markup=admin_cancel_kb())
        return
    if v <= 0:
        await message.answer("Должно быть > 0.", reply_markup=admin_cancel_kb())
        return
    await state.clear()
    async with session_factory() as session:
        await set_setting(session, "stars_rub_per_star", str(v))
    await message.answer(f"Сохранено: 1★ = {v} ₽", reply_markup=admin_back_home_kb())


@router.message(F.text == A_OUTREACH)
async def out_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(OutreachFSM.user_ref)
    await message.answer(
        f"✉️ <b>Сообщение пользователю</b>\n\n{blockquote('Кому: @username или Telegram ID.')}",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(OutreachFSM.user_ref, F.text)
async def out_user(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(ref=(message.text or "").strip())
    await state.set_state(OutreachFSM.message)
    await message.answer("Текст сообщения:", reply_markup=admin_cancel_kb())


@router.message(OutreachFSM.message, F.text)
async def out_send(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    ref = data.get("ref", "")
    txt = (message.text or "").strip()[:3500]
    await state.clear()
    async with session_factory() as session:
        u = await resolve_user_ref(session, ref)
        if not u:
            await message.answer("Не найден.", reply_markup=admin_back_home_kb())
            return
        tid = u.telegram_id
    try:
        await message.bot.send_message(tid, txt)
        un = f"@{u.username}" if u.username else "без username"
        await message.answer(
            f"✅ Отправлено\n\n{section('Получатель', f'{un}\nID <code>{tid}</code>')}",
            parse_mode="HTML",
            reply_markup=admin_back_home_kb(),
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await message.answer(f"Ошибка: {e}", reply_markup=admin_back_home_kb())


@router.message(F.text == A_PF_ADD)
async def pf_add_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(PlatformAddFSM.name)
    await message.answer("Название сервиса:", reply_markup=admin_cancel_kb())


@router.message(PlatformAddFSM.name, F.text)
async def pf_name(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(PlatformAddFSM.slug)
    await message.answer("Slug (латиница):", reply_markup=admin_cancel_kb())


@router.message(PlatformAddFSM.slug, F.text)
async def pf_slug(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(slug=(message.text or "").strip())
    await state.set_state(PlatformAddFSM.cooldown)
    await message.answer(COOLDOWN_HOURS_PROMPT, reply_markup=admin_cancel_kb(), parse_mode="HTML")


@router.message(PlatformAddFSM.cooldown, F.text)
async def pf_cd_save(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    hours = parse_cooldown_hours(message.text or "")
    if hours is None:
        await message.answer(COOLDOWN_HOURS_INVALID, reply_markup=admin_cancel_kb(), parse_mode="HTML")
        return
    cd = hours_to_cooldown_seconds(hours)
    data = await state.get_data()
    await state.clear()
    async with session_factory() as session:
        p = await create_platform(session, data.get("name", ""), data.get("slug", ""), cd)
    if not p:
        await message.answer("Slug занят.", reply_markup=admin_back_home_kb())
        return
    await message.answer(
        f"✅ {p.name} ({p.slug})\nКулдаун: {format_cooldown_hours(p.cooldown_seconds)}",
        reply_markup=admin_back_home_kb(),
    )


@router.message(F.text == A_PF_DEL)
async def pf_del_menu(message: Message, session_factory: async_sessionmaker[AsyncSession], settings: Settings):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        pls = await list_platforms_all(session)
    labels = [delete_platform_label(p.id, p.name) for p in pls if p.slug != "default"]
    if not labels:
        await message.answer("Нечего удалять.", reply_markup=admin_back_home_kb())
        return
    await message.answer(
        f"🗑 <b>Удаление сервиса</b>\n\n{blockquote('Задания перейдут на сервис «Общее».')}",
        reply_markup=admin_labeled_list_kb(labels, [BTN_ADMIN_HOME]),
        parse_mode="HTML",
    )


@router.message(F.text.func(lambda t: parse_delete_platform(t) is not None))
async def pf_del_do(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_delete_platform(message.text or "")
    if pid is None:
        return
    async with session_factory() as session:
        default_p = await get_default_platform(session)
        def_id = default_p.id if default_p else 1
        ok = await delete_platform(session, pid, def_id)
    await message.answer(
        "Удалено." if ok else "Не удалось.",
        reply_markup=admin_back_home_kb(),
    )


@router.message(F.text == A_PF_CD)
async def pf_cd_menu(message: Message, session_factory: async_sessionmaker[AsyncSession], settings: Settings):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        pls = await list_platforms_all(session)
    labels = [cooldown_platform_label(p.id, p.name, p.cooldown_seconds) for p in pls]
    await message.answer(
        f"⏱ <b>Кулдауны сервисов</b>\n\n{blockquote('Выберите сервис.')}",
        reply_markup=admin_labeled_list_kb(labels, [BTN_ADMIN_HOME]),
        parse_mode="HTML",
    )


@router.message(F.text.func(lambda t: parse_cooldown_platform(t) is not None))
async def pf_cd_pick(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_cooldown_platform(message.text or "")
    if pid is None:
        return
    await state.set_state(PlatformCdFSM.seconds)
    await state.update_data(pf_id=pid)
    await message.answer(COOLDOWN_HOURS_PROMPT, reply_markup=admin_cancel_kb(), parse_mode="HTML")


@router.message(PlatformCdFSM.seconds, F.text)
async def pf_cd_apply(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    hours = parse_cooldown_hours(message.text or "")
    if hours is None:
        await message.answer(COOLDOWN_HOURS_INVALID, reply_markup=admin_cancel_kb(), parse_mode="HTML")
        return
    seconds = hours_to_cooldown_seconds(hours)
    data = await state.get_data()
    pid = int(data.get("pf_id", 0))
    await state.clear()
    async with session_factory() as session:
        ok = await update_platform_cooldown(session, pid, seconds)
    await message.answer(
        f"Сохранено: {format_cooldown_hours(seconds)}." if ok else "Ошибка.",
        reply_markup=admin_back_home_kb(),
    )

