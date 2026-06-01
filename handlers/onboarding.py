from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from handlers.formatting import blockquote, onboarding_welcome, section
from handlers.keyboards import BTN_GENDER_F, BTN_GENDER_M, onboarding_gender_kb, user_main_kb
from handlers.menu_common import send_main_menu
from repo import complete_onboarding, ensure_user, get_user_by_referral_code

router = Router(name="onboarding")


class OnboardingFSM(StatesGroup):
    gender = State()
    platform_name = State()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    await state.clear()
    args = (message.text or "").split(maxsplit=1)
    ref_id: int | None = None
    if len(args) > 1 and args[1].upper().startswith("REF_"):
        code = args[1][4:].upper().strip()
        async with session_factory() as session:
            inviter = await get_user_by_referral_code(session, code)
            if inviter and inviter.telegram_id != message.from_user.id:
                ref_id = inviter.id

    fu = message.from_user
    async with session_factory() as session:
        u = await ensure_user(
            session,
            fu.id,
            fu.username,
            referred_by_id=ref_id,
            first_name=fu.first_name,
            last_name=fu.last_name,
        )

    if u.onboarding_completed:
        await send_main_menu(message, u, settings)
        return

    await state.set_state(OnboardingFSM.gender)
    await message.answer(
        onboarding_welcome(fu),
        reply_markup=onboarding_gender_kb(),
        parse_mode="HTML",
    )


@router.message(OnboardingFSM.gender, F.text)
async def ob_gender(message: Message, state: FSMContext):
    if message.text not in (BTN_GENDER_M, BTN_GENDER_F):
        await message.answer(
            "Выберите пол кнопкой на клавиатуре ниже.",
            reply_markup=onboarding_gender_kb(),
        )
        return
    g = "male" if message.text == BTN_GENDER_M else "female"
    await state.update_data(gender=g)
    await state.set_state(OnboardingFSM.platform_name)
    await message.answer(
        f"Шаг 2 из 2\n\n"
        f"{section('Вопрос', 'Как вас зовут / какой ник на платформах (Яндекс Карты, 2ГИС, Google и т.д.)?')}\n\n"
        f"{blockquote('Напишите одним сообщением — так мы подберём подходящие тексты отзывов.')}",
        parse_mode="HTML",
    )


@router.message(OnboardingFSM.platform_name, F.text)
async def ob_platform_name(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Напишите имя или ник (минимум 2 символа).")
        return
    data = await state.get_data()
    gender = data.get("gender")
    if gender not in ("male", "female"):
        await state.clear()
        await message.answer("Начните с /start")
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
        u = await complete_onboarding(session, u.id, gender, name)
    await state.clear()
    if not u:
        await message.answer("Ошибка сохранения. Попробуйте /start")
        return
    await message.answer(
        f"✅ <b>Опрос завершён</b>\n\n"
        f"{blockquote('Доступны все разделы бота. В «Заданиях» — готовый текст и ссылка на задание.')}",
        parse_mode="HTML",
    )
    await send_main_menu(message, u, settings)
