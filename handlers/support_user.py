from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.filters import OnboardingCompletedFilter
from handlers.keyboards import (
    BTN_BACK_MENU,
    BTN_SUPPORT,
    BTN_SUPPORT_NO_SCREEN,
    support_photo_kb,
    user_back_menu_kb,
)
from handlers.menu_common import return_to_main_menu, send_main_menu
from handlers.support_states import SupportUserFSM
from repo import create_support_ticket, ensure_user

router = Router(name="support_user")
router.message.filter(OnboardingCompletedFilter())

SUPPORT_INTRO = (
    "Перед тем, как написать своё обращение в поддержку, "
    "проверьте, нет ли Вашего вопроса в <b>F.A.Q</b>.\n\n"
    "Опишите проблему одним сообщением."
)


@router.message(F.text == BTN_SUPPORT)
async def support_start(message: Message, state: FSMContext):
    await state.set_state(SupportUserFSM.waiting_text)
    await message.answer(SUPPORT_INTRO, parse_mode="HTML", reply_markup=user_back_menu_kb())


@router.message(SupportUserFSM.waiting_text, F.text)
async def support_text(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    text = (message.text or "").strip()
    if text == BTN_BACK_MENU:
        await state.clear()
        async with session_factory() as session:
            u = await ensure_user(
                session,
                message.from_user.id,
                message.from_user.username,
                referred_by_id=None,
            )
        await send_main_menu(message, u, settings)
        return
    if not text:
        await message.answer("Опишите проблему одним сообщением.")
        return
    if text in {BTN_SUPPORT, BTN_SUPPORT_NO_SCREEN}:
        await message.answer("Опишите проблему текстом.")
        return
    await state.update_data(support_text=text)
    await state.set_state(SupportUserFSM.waiting_photo)
    await message.answer(
        "Пришлите скриншот (фото) или нажмите «Нет», если скрина нет.",
        reply_markup=support_photo_kb(),
    )


@router.message(SupportUserFSM.waiting_photo, F.photo)
async def support_photo(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    photo_id = message.photo[-1].file_id
    await _finish_support(message, state, session_factory, settings, photo_id)


@router.message(SupportUserFSM.waiting_photo, F.text)
async def support_photo_skip(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    raw = (message.text or "").strip()
    if raw == BTN_BACK_MENU:
        await state.clear()
        async with session_factory() as session:
            u = await ensure_user(
                session,
                message.from_user.id,
                message.from_user.username,
                referred_by_id=None,
            )
        await send_main_menu(message, u, settings)
        return
    if raw.lower() != BTN_SUPPORT_NO_SCREEN.lower() and raw != BTN_SUPPORT_NO_SCREEN:
        await message.answer(
            "Отправьте фото или нажмите «Нет».",
            reply_markup=support_photo_kb(),
        )
        return
    await _finish_support(message, state, session_factory, settings, None)


async def _finish_support(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    photo_file_id: str | None,
) -> None:
    data = await state.get_data()
    body = (data.get("support_text") or "").strip()
    if not body:
        await state.clear()
        await message.answer("Текст обращения не найден. Начните снова: «Поддержка».")
        return
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
        )
        ticket = await create_support_ticket(session, u.id, body, photo_file_id)
    await state.clear()
    await message.answer(
        "✅ Обращение отправлено. Ожидайте ответа поддержки.",
        reply_markup=user_back_menu_kb(),
    )

@router.message(F.text == BTN_BACK_MENU, StateFilter(SupportUserFSM))
async def support_cancel_menu(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    await return_to_main_menu(message, state, session_factory, settings)
