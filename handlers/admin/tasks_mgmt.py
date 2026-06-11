from __future__ import annotations

from datetime import datetime

import pandas as pd
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import Platform
from handlers.admin.common import is_admin
from handlers.admin.states import AdminImport, CustomerAddFSM, DeleteTextsFSM, ManualTextFSM, TaskRewardFSM
from handlers.formatting import blockquote, section
from handlers.keyboards import (
    BTN_CANCEL_INPUT,
    A_POOL_ADD,
    A_POOL_DEL,
    A_POOL_DEL_CUST,
    A_POOL_IMP,
    A_POOL_REWARD,
    A_POOL_REFRESH,
    A_TASK_CHANGE_REWARD,
    A_TASK_CREATE,
    A_TASK_LIST,
    A_TASKS,
    BTN_ADMIN_HOME,
    BTN_BACK_TASK_LIST,
    BTN_BACK_TASKS_ROOT,
    BTN_GENDER_F,
    BTN_GENDER_M,
    admin_back_home_kb,
    admin_cancel_kb,
    admin_labeled_list_kb,
    admin_pool_kb,
    admin_tasks_root_kb,
    parse_platform_pick,
    admin_task_pick_label,
    parse_admin_task_pick,
    platform_pick_label,
)
from services.yandex_maps import is_yandex_maps_slug
from repo import (
    add_task_text,
    create_customer_task,
    delete_task,
    delete_task_texts_by_numbers,
    get_task,
    list_all_tasks,
    list_platforms_all,
    update_task_fields,
)
from services.reward_input import format_reward_rub, parse_reward_amount
from services.text_pool import build_pool_lines, format_pool_message, parse_number_list
from services.timezone_util import publish_at_midnight

router = Router(name="admin_tasks")


async def send_pool_message(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    tid: int,
    settings: Settings,
) -> None:
    async with session_factory() as session:
        t = await get_task(session, tid)
    if not t:
        return
    lines = build_pool_lines(t.texts or [])
    text = format_pool_message(t, lines)
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=admin_pool_kb(),
        disable_web_page_preview=True,
    )


@router.message(F.text == A_TASKS)
@router.message(F.text == BTN_BACK_TASKS_ROOT)
async def msg_tasks_root(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await message.answer(
        f"📁 <b>Заказчики и тексты</b>\n\n{blockquote('Создайте заказчика или откройте список.')}",
        reply_markup=admin_tasks_root_kb(),
        parse_mode="HTML",
    )


@router.message(F.text == A_TASK_CREATE)
async def tadd_start(
    message: Message,
    settings: Settings,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        pls = await list_platforms_all(session)
    labels = [platform_pick_label(p.id, p.name) for p in pls]
    await state.set_state(CustomerAddFSM.platform_pick)
    await message.answer(
        f"➕ <b>Создание заказчика</b>\n\n"
        f"{blockquote('Сначала выберите сервис. Для «Яндекс Карты» — отдельный сценарий с тестом. '
                       'Для остальных — заказчик, ссылка, оплата и текст.')}",
        reply_markup=admin_labeled_list_kb(labels, [BTN_ADMIN_HOME]),
        parse_mode="HTML",
    )


@router.message(CustomerAddFSM.name, F.text)
async def tadd_name(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(customer_name=(message.text or "").strip())
    await state.set_state(CustomerAddFSM.link)
    await message.answer("Ссылка (http…):", reply_markup=admin_cancel_kb())


@router.message(CustomerAddFSM.link, F.text)
async def tadd_link(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    link = (message.text or "").strip()
    if link in ("-", "нет", "no") or len(link) < 8:
        await message.answer("Нужна полноценная ссылка.", reply_markup=admin_cancel_kb())
        return
    await state.update_data(link=link)
    await state.set_state(CustomerAddFSM.reward)
    await message.answer(
        "Оплата за один отзыв (₽), например <code>150</code> или <code>250.50</code>:",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(CustomerAddFSM.reward, F.text)
async def tadd_reward(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    rw = parse_reward_amount(message.text or "")
    if rw is None:
        await message.answer(
            "Введите сумму числом (0 или больше), например 200.",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.update_data(reward=rw)
    data = await state.get_data()
    if data.get("is_yandex"):
        await state.set_state(CustomerAddFSM.customer_region)
        await message.answer(
            f"Сумма: <b>{format_reward_rub(rw)}</b>.\n\n"
            "Регион заказчика (город/область), например <code>Москва</code>.\n"
            "Можно «нет» — тогда подходит любой регион.",
            reply_markup=admin_cancel_kb(),
            parse_mode="HTML",
        )
        return
    await state.set_state(CustomerAddFSM.instruction)
    await message.answer(
        f"Сумма: <b>{format_reward_rub(rw)}</b>.\n\n"
        "Текст / инструкция к заданию (или «нет»):",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(CustomerAddFSM.instruction, F.text)
async def tadd_instruction(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    raw = (message.text or "").strip()
    instr = "" if raw.lower() in ("-", "нет", "no", "нету") else raw
    await state.update_data(instruction=instr[:10000])
    data = await state.get_data()
    if data.get("is_yandex"):
        await state.set_state(CustomerAddFSM.org_address)
        await message.answer(
            "Адрес организации (для карточки задания):",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.set_state(CustomerAddFSM.customer_region)
    await message.answer(
        "Регион заказчика (город/область), например <code>Москва</code>.\n"
        "Можно «нет» — тогда подходит любой регион.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(CustomerAddFSM.platform_pick, F.text.func(lambda t: parse_platform_pick(t) is not None))
async def tadd_pf(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
    pid = parse_platform_pick(message.text or "")
    if pid is None:
        return
    async with session_factory() as session:
        pf = await session.get(Platform, pid)
    if not pf:
        await message.answer("Сервис не найден.", reply_markup=admin_cancel_kb())
        return
    ym = is_yandex_maps_slug(pf.slug)
    await state.update_data(platform_id=pid, is_yandex=ym, platform_name=pf.name)
    await state.set_state(CustomerAddFSM.name)
    if ym:
        hint = (
            f"Сервис: <b>{pf.name}</b> (сценарий с тестом)\n\n"
            "Название организации (заказчика):"
        )
    else:
        hint = (
            f"Сервис: <b>{pf.name}</b>\n\n"
            "Название заказчика (задания):"
        )
    await message.answer(hint, reply_markup=admin_cancel_kb(), parse_mode="HTML")


@router.message(CustomerAddFSM.customer_region, F.text)
async def tadd_customer_region(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    raw = (message.text or "").strip()
    reg = "" if raw.lower() in ("-", "нет", "no", "нету", "любой", "все") else raw[:255]
    await state.update_data(customer_region=reg)
    data = await state.get_data()
    if data.get("is_yandex"):
        await state.set_state(CustomerAddFSM.instruction)
        await message.answer(
            "Краткая инструкция к заданию (или «нет»):",
            reply_markup=admin_cancel_kb(),
        )
        return
    await _create_customer_from_state(message, state, session_factory, settings)


async def _create_customer_from_state(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    yandex_question_order: str | None = None,
) -> None:
    data = await state.get_data()
    pid = int(data.get("platform_id") or 0)
    await state.clear()
    async with session_factory() as session:
        t, err = await create_customer_task(
            session,
            data.get("customer_name", ""),
            data.get("link", ""),
            pid,
            float(data.get("reward", 0) or 0),
            data.get("instruction", ""),
            org_address=data.get("org_address", "") if data.get("is_yandex") else None,
            region=data.get("customer_region", ""),
            yandex_question_order=yandex_question_order,
        )
    if err:
        await message.answer(err, reply_markup=admin_tasks_root_kb())
        return
    rw = float(t.reward or 0)
    reg = t.region or "любой"
    extra = ""
    if yandex_question_order:
        extra = f"\nТест (порядок вопросов): <code>{yandex_question_order}</code>"
    await message.answer(
        f"✅ Заказчик создан.\nРегион: <b>{reg}</b>\n"
        f"Оплата за отзыв: <b>{format_reward_rub(rw)}</b>{extra}",
        reply_markup=admin_pool_kb(),
        parse_mode="HTML",
    )
    await state.update_data(pool_task_id=t.id)
    await send_pool_message(message, session_factory, t.id, settings)


@router.message(CustomerAddFSM.org_address, F.text)
async def tadd_org_address(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(org_address=(message.text or "").strip()[:1024])
    await _create_customer_from_state(message, state, session_factory, settings)


async def _send_task_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    for_reward: bool = False,
) -> None:
    async with session_factory() as session:
        tasks = await list_all_tasks(session)
    if not tasks:
        await message.answer("Пусто.", reply_markup=admin_tasks_root_kb())
        return
    labels = [
        admin_task_pick_label(
            t.id, t.customer_name or t.title or "", t.reward or 0, t.region
        )
        for t in tasks[:40]
    ]
    if for_reward:
        hint = "Выберите заказчика, у которого изменить оплату за отзыв."
        nav = [BTN_BACK_TASKS_ROOT, BTN_ADMIN_HOME]
    else:
        hint = "Выберите заказчика. Оплату за отзыв можно изменить кнопкой «Изменить оплату» в карточке заказчика."
        nav = [BTN_BACK_TASKS_ROOT, BTN_ADMIN_HOME]
    await message.answer(
        f"📋 <b>Заказчики</b>\n\n{blockquote(hint)}",
        reply_markup=admin_labeled_list_kb(labels, nav),
        parse_mode="HTML",
    )


@router.message(F.text == A_TASK_LIST)
@router.message(F.text == BTN_BACK_TASK_LIST)
async def tlsk(message: Message, session_factory: async_sessionmaker[AsyncSession], settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await _send_task_list(message, session_factory, for_reward=False)


@router.message(F.text == A_TASK_CHANGE_REWARD)
async def tchange_reward_list(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await state.update_data(task_pick_mode="reward")
    await _send_task_list(message, session_factory, for_reward=True)


@router.message(F.text.func(lambda t: parse_admin_task_pick(t) is not None))
async def tv(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    tid = parse_admin_task_pick(message.text or "")
    if tid is None:
        return
    data = await state.get_data()
    if data.get("task_pick_mode") == "reward":
        async with session_factory() as session:
            t = await get_task(session, tid)
        if not t:
            await state.clear()
            await message.answer("Заказчик не найден.", reply_markup=admin_tasks_root_kb())
            return
        cur = format_reward_rub(t.reward or 0)
        await state.set_state(TaskRewardFSM.amount)
        await state.update_data(pool_task_id=tid, reward_task_id=tid, task_pick_mode=None)
        await message.answer(
            f"Заказчик: <b>{t.customer_name or t.title}</b>\n"
            f"Сейчас: <b>{cur}</b>\n\n"
            "Новая оплата за один отзыв (₽):",
            reply_markup=admin_cancel_kb(),
            parse_mode="HTML",
        )
        return
    await state.clear()
    await state.update_data(pool_task_id=tid)
    await send_pool_message(message, session_factory, tid, settings)


@router.message(TaskRewardFSM.amount, F.text == BTN_CANCEL_INPUT)
async def pool_reward_cancel(
    message: Message,
    settings: Settings,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
    data = await state.get_data()
    tid = int(data.get("reward_task_id") or data.get("pool_task_id") or 0)
    await state.clear()
    if tid:
        await state.update_data(pool_task_id=tid)
        await send_pool_message(message, session_factory, tid, settings)
        return
    await message.answer("Отменено.", reply_markup=admin_tasks_root_kb())


@router.message(F.text == A_POOL_REWARD)
async def pool_reward_start(
    message: Message,
    settings: Settings,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
    tid = (await state.get_data()).get("pool_task_id")
    if not tid:
        await message.answer("Сначала откройте заказчика из списка.")
        return
    async with session_factory() as session:
        t = await get_task(session, int(tid))
    cur = format_reward_rub((t.reward if t else 0) or 0)
    await state.set_state(TaskRewardFSM.amount)
    await state.update_data(reward_task_id=int(tid))
    await message.answer(
        f"Сейчас: <b>{cur}</b>\n\nНовая оплата за один отзыв (₽):",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(TaskRewardFSM.amount, F.text)
async def pool_reward_save(
    message: Message,
    settings: Settings,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    rw = parse_reward_amount(message.text or "")
    if rw is None:
        await message.answer("Введите сумму числом.", reply_markup=admin_cancel_kb())
        return
    data = await state.get_data()
    tid = int(data.get("reward_task_id") or data.get("pool_task_id") or 0)
    if not tid:
        await state.clear()
        return
    async with session_factory() as session:
        t = await update_task_fields(session, tid, reward=rw)
    await state.clear()
    await state.update_data(pool_task_id=tid)
    if not t:
        await message.answer("Заказчик не найден.", reply_markup=admin_tasks_root_kb())
        return
    await message.answer(
        f"✅ Оплата: <b>{format_reward_rub(t.reward)}</b>",
        reply_markup=admin_pool_kb(),
        parse_mode="HTML",
    )
    await send_pool_message(message, session_factory, tid, settings)


@router.message(F.text == A_POOL_REFRESH)
async def pool_refresh(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    if not is_admin(message.from_user.id, settings):
        return
    tid = (await state.get_data()).get("pool_task_id")
    if not tid:
        await message.answer("Сначала откройте заказчика из списка.")
        return
    await send_pool_message(message, session_factory, int(tid), settings)


@router.message(F.text == A_POOL_ADD)
async def ttadd(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    tid = (await state.get_data()).get("pool_task_id")
    if not tid:
        await message.answer("Сначала откройте заказчика.")
        return
    await state.set_state(ManualTextFSM.gender)
    await state.update_data(task_id=int(tid))
    from handlers.keyboards import _kb, _rows

    await message.answer(
        "Пол текста:",
        reply_markup=_kb(_rows(BTN_GENDER_M, BTN_GENDER_F, BTN_ADMIN_HOME)),
    )


@router.message(ManualTextFSM.gender, F.text.in_({BTN_GENDER_M, BTN_GENDER_F}))
async def mtg(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    g = "male" if message.text == BTN_GENDER_M else "female"
    await state.update_data(gender=g)
    await state.set_state(ManualTextFSM.body)
    await message.answer("Текст отзыва:", reply_markup=admin_cancel_kb())


@router.message(ManualTextFSM.body, F.text)
async def mt_body(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(body=(message.text or "").strip())
    await state.set_state(ManualTextFSM.publish_date)
    await message.answer(
        "Дата (ДД.ММ.ГГГГ) или «сейчас»:",
        reply_markup=admin_cancel_kb(),
    )


@router.message(ManualTextFSM.publish_date, F.text)
async def mt_date(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    raw = (message.text or "").strip().lower()
    data = await state.get_data()
    tid = int(data["task_id"])
    publish_at = None
    published = True
    if raw not in ("-", "сейчас", "now", "нет"):
        try:
            d = pd.to_datetime(raw, dayfirst=True).date()
            publish_at = publish_at_midnight(d, settings.app_timezone)
            published = publish_at <= datetime.utcnow()
        except Exception:
            await message.answer("Формат: 09.05.2026 или «сейчас».", reply_markup=admin_cancel_kb())
            return
    await state.clear()
    await state.update_data(pool_task_id=tid)
    async with session_factory() as session:
        tt = await add_task_text(
            session,
            tid,
            data.get("body", ""),
            required_gender=data.get("gender"),
            publish_at=publish_at,
            published=published,
        )
    await message.answer(f"Добавлен текст №{tt.text_number}.", reply_markup=admin_pool_kb())
    await send_pool_message(message, session_factory, tid, settings)


@router.message(F.text == A_POOL_DEL)
async def tdelnums_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    tid = (await state.get_data()).get("pool_task_id")
    if not tid:
        await message.answer("Сначала откройте заказчика.")
        return
    await state.set_state(DeleteTextsFSM.numbers)
    await state.update_data(task_id=int(tid))
    await message.answer(
        "Удаление текста: укажите номера через запятую (например 2, 3):",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(DeleteTextsFSM.numbers, F.text)
async def tdelnums_do(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    tid = int((await state.get_data()).get("task_id", 0))
    await state.clear()
    await state.update_data(pool_task_id=tid)
    nums = parse_number_list(message.text or "")
    async with session_factory() as session:
        deleted, notes = await delete_task_texts_by_numbers(session, tid, nums)
    lines = [f"Удалено: {deleted}."]
    if notes:
        lines.extend(notes)
    await message.answer("\n".join(lines), reply_markup=admin_pool_kb())
    await send_pool_message(message, session_factory, tid, settings)


@router.message(F.text == A_POOL_IMP)
async def tpoolimp(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    tid = (await state.get_data()).get("pool_task_id")
    if not tid:
        await message.answer("Сначала откройте заказчика.")
        return
    await state.set_state(AdminImport.waiting_file)
    await state.update_data(pool_task_id=int(tid))
    await message.answer(
        "Пришлите .xlsx для этого заказчика.",
        reply_markup=admin_cancel_kb(),
    )


@router.message(F.text == A_POOL_DEL_CUST)
async def tdel(message: Message, session_factory: async_sessionmaker[AsyncSession], settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    tid = (await state.get_data()).get("pool_task_id")
    if not tid:
        await message.answer("Сначала откройте заказчика.")
        return
    async with session_factory() as session:
        await delete_task(session, int(tid))
    await state.clear()
    await message.answer("Заказчик удалён.", reply_markup=admin_tasks_root_kb())
