from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.admin.common import is_admin
from handlers.admin.states import YandexQuizFSM
from handlers.formatting import blockquote, section
from handlers.keyboards import (
    A_YM_QUIZ,
    BTN_YM_QUIZ_EDIT,
    BTN_YM_QUIZ_LIST,
    BTN_YM_QUIZ_ORDER,
    admin_cancel_kb,
    admin_ym_quiz_kb,
)
from repo import (
    get_yandex_quiz_default_order,
    list_all_yandex_questions,
    set_yandex_quiz_default_order,
    update_yandex_question,
)
from services.yandex_maps import (
    YANDEX_QUIZ_MAX_COUNT,
    YANDEX_QUIZ_MAX_SLOT,
    YANDEX_QUIZ_MIN_COUNT,
    parse_question_order,
)

router = Router(name="admin_yandex_quiz")


async def _quiz_summary(session: AsyncSession) -> str:
    order_csv = await get_yandex_quiz_default_order(session)
    order, _ = parse_question_order(order_csv)
    count = len(order) if order else 0
    return (
        f"Сейчас в тесте: <b>{count}</b> вопросов\n"
        f"Порядок слотов: <code>{order_csv}</code>\n\n"
        f"{blockquote('Тест показывается только при выдаче заданий на Яндекс Картах.')}"
    )


async def _questions_list_text(session: AsyncSession) -> str:
    rows = await list_all_yandex_questions(session)
    lines: list[str] = []
    for q in rows:
        mark = "✅" if q.active else "⏸"
        body = (q.body or "").strip()
        if len(body) > 120:
            body = body[:117] + "…"
        lines.append(f"{mark} <b>{q.slot}.</b> {body}")
    return section("Вопросы (слоты 1–15)", "\n".join(lines) if lines else "Пусто")


@router.message(F.text == A_YM_QUIZ)
async def ym_quiz_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.clear()
    await message.answer(
        "📝 <b>Тест Яндекс Карт</b>\n\n"
        "Настройка контрольных вопросов перед выдачей текста отзыва.",
        reply_markup=admin_ym_quiz_kb(),
        parse_mode="HTML",
    )


@router.message(F.text == BTN_YM_QUIZ_LIST)
async def ym_quiz_list(
    message: Message,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        return
    async with session_factory() as session:
        text = await _questions_list_text(session)
        summary = await _quiz_summary(session)
    await message.answer(
        f"{summary}\n\n{text}",
        parse_mode="HTML",
        reply_markup=admin_ym_quiz_kb(),
    )


@router.message(F.text == BTN_YM_QUIZ_ORDER)
async def ym_quiz_order_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(YandexQuizFSM.order)
    await message.answer(
        f"Введите номера слотов через запятую.\n"
        f"От <b>{YANDEX_QUIZ_MIN_COUNT}</b> до <b>{YANDEX_QUIZ_MAX_COUNT}</b> вопросов, "
        f"слоты 1–{YANDEX_QUIZ_MAX_SLOT} без повторов.\n\n"
        "Пример 10 вопросов:\n<code>1,2,3,4,5,6,7,8,9,10</code>\n\n"
        "Пример 12 вопросов:\n<code>1,2,3,4,5,6,7,8,9,10,11,12</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(YandexQuizFSM.order, F.text)
async def ym_quiz_order_save(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    async with session_factory() as session:
        saved, err = await set_yandex_quiz_default_order(session, message.text or "")
        if err:
            await message.answer(err, reply_markup=admin_cancel_kb())
            return
        summary = await _quiz_summary(session)
    await state.clear()
    await message.answer(
        f"✅ Порядок сохранён: <code>{saved}</code>\n\n{summary}",
        parse_mode="HTML",
        reply_markup=admin_ym_quiz_kb(),
    )


@router.message(F.text == BTN_YM_QUIZ_EDIT)
async def ym_quiz_edit_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(YandexQuizFSM.edit_slot)
    await message.answer(
        f"Номер слота вопроса (1–{YANDEX_QUIZ_MAX_SLOT}):",
        reply_markup=admin_cancel_kb(),
    )


@router.message(YandexQuizFSM.edit_slot, F.text)
async def ym_quiz_edit_slot(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    try:
        slot = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите число слота.", reply_markup=admin_cancel_kb())
        return
    if slot < 1 or slot > YANDEX_QUIZ_MAX_SLOT:
        await message.answer(
            f"Слот от 1 до {YANDEX_QUIZ_MAX_SLOT}.",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.update_data(edit_slot=slot)
    await state.set_state(YandexQuizFSM.edit_body)
    await message.answer(
        f"Слот <b>{slot}</b>. Отправьте новый текст вопроса.\n"
        "Чтобы выключить вопрос — отправьте <code>-</code>\n"
        "Чтобы включить снова — начните текст с <code>+</code>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(YandexQuizFSM.edit_body, F.text)
async def ym_quiz_edit_body(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    slot = int(data.get("edit_slot") or 0)
    raw = (message.text or "").strip()
    active: bool | None = None
    body = raw
    if raw == "-":
        active = False
        body = None
    elif raw.startswith("+"):
        active = True
        body = raw[1:].strip()
    if body is not None and not body and active is not False:
        await message.answer("Текст не может быть пустым.", reply_markup=admin_cancel_kb())
        return
    async with session_factory() as session:
        q = await update_yandex_question(
            session,
            slot,
            body=body,
            active=active,
        )
        if not q:
            await message.answer("Слот не найден.", reply_markup=admin_ym_quiz_kb())
            await state.clear()
            return
    await state.clear()
    status = "включён" if q.active else "выключен"
    await message.answer(
        f"✅ Слот <b>{slot}</b> обновлён ({status}).\n\n{blockquote(q.body)}",
        parse_mode="HTML",
        reply_markup=admin_ym_quiz_kb(),
    )

