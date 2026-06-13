from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import Platform, SubmissionStatus, TaskText
from handlers.filters import OnboardingCompletedFilter
from handlers.formatting import blockquote, esc_html, section
from handlers.keyboards import (
    BTN_BACK_MENU,
    BTN_BACK_PLATFORMS,
    BTN_GENDER_F,
    BTN_GENDER_M,
    parse_user_platform_pick,
    user_main_kb,
    user_platforms_kb,
)
from handlers.menu_common import return_to_main_menu, send_main_menu
from handlers.yandex_maps.filters import ActiveYandexFlowFilter, YandexPlatformPickFilter
from handlers.yandex_maps.keyboards import (
    BTN_YM_GET,
    BTN_YM_NO,
    BTN_YM_Q_NO,
    BTN_YM_Q_YES,
    BTN_YM_REFUSE,
    BTN_YM_RESET,
    BTN_YM_START,
    BTN_YM_YES,
    ym_conditions_kb,
    ym_gender_kb,
    ym_question_kb,
    ym_quiz_intro_kb,
    ym_website_kb,
    ym_yes_no_kb,
)
from handlers.yandex_maps.states import YandexMapsUserFSM
from repo import (
    ban_user_for_days,
    claim_yandex_assignment,
    clear_ym_session,
    complete_onboarding,
    create_submission,
    ensure_user,
    get_active_ym_session,
    get_submission_for_user_task,
    get_task,
    get_yandex_conditions,
    release_task_text,
    release_ym_assignment,
    reset_incomplete_ym_flow,
    save_ym_session,
    start_ym_session,
    task_platform_is_yandex,
    user_is_banned_now,
    YM_AWAIT_REVIEW_MSG,
)
from services.yandex_maps import (
    YANDEX_QUIZ_POOL_SIZE,
    format_question_order,
    format_quiz_freeze_duration,
    is_yandex_maps_slug,
)
from services.yandex_quiz import (
    answer_is_too_fast,
    list_yandex_questions_for_ym_session,
    pick_random_quiz_slots,
)

router = Router(name="yandex_maps_user")
router.message.filter(OnboardingCompletedFilter())


@router.message(F.text == BTN_BACK_MENU)
async def ym_goto_main_menu(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    state: FSMContext,
):
    await return_to_main_menu(message, state, session_factory, settings)


async def _platform_id_from_pick(session: AsyncSession, text: str | None) -> int | None:
    pid = parse_user_platform_pick(text)
    if pid is None:
        return None
    p = await session.get(Platform, pid)
    if not p or not is_yandex_maps_slug(p.slug):
        return None
    return pid


@router.message(YandexPlatformPickFilter())
async def ym_platform_entry(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    await state.clear()
    async with session_factory() as session:
        pid = await _platform_id_from_pick(session, message.text)
        if pid is None:
            await message.answer("Сервис недоступен.", reply_markup=user_main_kb())
            return
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        if user_is_banned_now(u):
            await message.answer("Аккаунт заблокирован.")
            return
        ym = await get_active_ym_session(session, u.id)
        if ym and ym.step == "frozen":
            await message.answer(YM_AWAIT_REVIEW_MSG, reply_markup=user_main_kb())
            return
        cond = await get_yandex_conditions(session)
        await start_ym_session(session, u.id, "conditions")
        await state.update_data(ym_platform_id=pid)
    await message.answer(
        f"🗺 <b>Яндекс Карты</b>\n\n{section('Условия', cond)}",
        parse_mode="HTML",
        reply_markup=ym_conditions_kb(),
    )


@router.message(F.text == BTN_YM_GET, ActiveYandexFlowFilter())
async def ym_get_tasks(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    data = await state.get_data()
    if not data.get("ym_platform_id"):
        await message.answer("Сначала выберите «Яндекс Карты» в списке сервисов.")
        return
    async with session_factory() as session:
        u = await ensure_user(
            session,
            message.from_user.id,
            message.from_user.username,
            referred_by_id=None,
        )
        if user_is_banned_now(u):
            await message.answer("Аккаунт заблокирован.")
            return
        ym = await get_active_ym_session(session, u.id)
        if not ym or ym.step != "conditions":
            await message.answer("Сначала выберите «Яндекс Карты» в списке сервисов.")
            return
        if u.gender in ("male", "female"):
            acct = (u.platform_account_name or "").strip()
            if len(acct) >= 2:
                ym.step = "region"
                await save_ym_session(session, ym)
                await state.set_state(YandexMapsUserFSM.region)
                await message.answer(
                    f"{blockquote('Напишите ваш регион (город/область). Сначала выдаются задания из этого региона.')}",
                    parse_mode="HTML",
                    reply_markup=ym_conditions_kb(),
                )
                return
            ym.step = "yandex_account"
            await save_ym_session(session, ym)
            await state.set_state(YandexMapsUserFSM.yandex_account)
            await message.answer(
                "Имя аккаунта в <b>Яндекс ID</b> (как в профиле):",
                parse_mode="HTML",
                reply_markup=ym_conditions_kb(),
            )
            return
        ym.step = "gender"
        await save_ym_session(session, ym)
    await state.set_state(YandexMapsUserFSM.gender)
    await message.answer(
        f"🗺 <b>Яндекс Карты</b>\n\n{blockquote('Укажите ваш пол.')}",
        parse_mode="HTML",
        reply_markup=ym_gender_kb(),
    )


@router.message(YandexMapsUserFSM.gender, F.text.in_({BTN_GENDER_M, BTN_GENDER_F}), ActiveYandexFlowFilter())
async def ym_gender(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
):
    g = "male" if message.text == BTN_GENDER_M else "female"
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        u.gender = g
        ym = await get_active_ym_session(session, u.id)
        if ym:
            ym.step = "yandex_account"
            await save_ym_session(session, ym)
        await session.commit()
    await state.set_state(YandexMapsUserFSM.yandex_account)
    await message.answer(
        "Имя аккаунта в <b>Яндекс ID</b> (как в профиле):",
        parse_mode="HTML",
        reply_markup=ym_conditions_kb(),
    )


@router.message(YandexMapsUserFSM.yandex_account, F.text, ActiveYandexFlowFilter())
async def ym_account(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    raw = (message.text or "").strip()
    if raw == BTN_BACK_MENU:
        await return_to_main_menu(message, state, session_factory, settings)
        return
    if raw == BTN_BACK_PLATFORMS:
        await ym_back_platforms(message, session_factory, state, settings)
        return
    if raw == BTN_YM_GET:
        return
    if len(raw) < 2:
        await message.answer("Введите имя аккаунта Яндекс ID.")
        return
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        u.platform_account_name = raw[:512]
        ym = await get_active_ym_session(session, u.id)
        if ym:
            ym.step = "region"
            await save_ym_session(session, ym)
        await session.commit()
    await state.set_state(YandexMapsUserFSM.region)
    await message.answer(
        f"{blockquote('Напишите ваш регион (город/область). Сначала выдаются задания из этого региона.')}",
        parse_mode="HTML",
        reply_markup=ym_conditions_kb(),
    )


@router.message(YandexMapsUserFSM.region, F.text, ActiveYandexFlowFilter())
async def ym_region(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    region = (message.text or "").strip()
    if region == BTN_BACK_MENU:
        await return_to_main_menu(message, state, session_factory, settings)
        return
    if region == BTN_BACK_PLATFORMS:
        await ym_back_platforms(message, session_factory, state, settings)
        return
    if region in {BTN_YM_GET} or len(region) < 2:
        await message.answer("Укажите регион текстом.")
        return
    data = await state.get_data()
    pid = int(data.get("ym_platform_id") or 0)
    await state.set_state(None)
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        if not u.gender:
            await message.answer("Сначала укажите пол.", reply_markup=ym_gender_kb())
            await state.set_state(YandexMapsUserFSM.gender)
            return
        u.work_region = region[:255]
        ym = await get_active_ym_session(session, u.id)
        if not ym:
            ym = await start_ym_session(session, u.id, "assign")
        ym.region = region[:255]
        ym.step = "assign"
        await save_ym_session(session, ym)
        task, claimed = await claim_yandex_assignment(
            session, u.id, u.gender, region, pid
        )
        if not task or not claimed:
            await clear_ym_session(session, u.id)
            await message.answer(
                "Сейчас нет свободных заданий. Попробуйте позже или другой регион.",
                reply_markup=user_main_kb(),
            )
            return
        ym.task_id = task.id
        ym.task_text_id = claimed.id
        ym.step = "org"
        ym.question_index = 0
        await save_ym_session(session, ym)
        await state.update_data(ym_platform_id=pid, ym_task_id=task.id)
    await _send_org_info(message, session_factory, task.id)


async def _handle_quiz_cheat(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
    *,
    user_id: int,
    ym,
    min_seconds: int,
    ban_days: int,
) -> None:
    async with session_factory() as session:
        if ym and ym.task_text_id:
            await release_task_text(session, user_id, int(ym.task_text_id))
        await ban_user_for_days(session, user_id, ban_days)
        await clear_ym_session(session, user_id)
    await state.clear()
    await message.answer(
        f"⛔ <b>Слишком быстрый ответ</b>\n\n"
        f"{blockquote(f'Между показом вопроса и ответом должно пройти не менее {min_seconds} с. '
                       f'Аккаунт заблокирован на {ban_days} дн.')}",
        parse_mode="HTML",
        reply_markup=user_main_kb(),
    )


async def _send_org_info(message: Message, session_factory: async_sessionmaker[AsyncSession], task_id: int):
    async with session_factory() as session:
        t = await get_task(session, task_id)
    if not t:
        return
    addr = (t.org_address or "").strip() or "не указан администратором"
    reg = t.region or "любой"
    lines = [
        f"<b>Организация:</b> {esc_html(t.customer_name or t.title)}",
        f"<b>Регион:</b> {esc_html(reg)}",
        f"<b>Адрес:</b> {esc_html(addr)}",
    ]
    await message.answer(
        f"🗺 <b>Задание назначено</b>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"Найдите эту организацию в Яндекс Картах по адресу выше. Нашли?",
        parse_mode="HTML",
        reply_markup=ym_yes_no_kb(),
    )


@router.message(F.text.in_({BTN_YM_YES, BTN_YM_NO}), ActiveYandexFlowFilter())
async def ym_found(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    data = await state.get_data()
    pid = int(data.get("ym_platform_id") or 0)
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        ym = await get_active_ym_session(session, u.id)
        if not ym or ym.step not in ("org", "assign_retry") or not ym.task_id:
            return
        if not await task_platform_is_yandex(session, ym.task_id):
            return
        if message.text == BTN_YM_NO:
            if ym.task_text_id:
                await release_ym_assignment(session, u.id, int(ym.task_text_id))
            ym.task_id = None
            ym.task_text_id = None
            ym.step = "assign"
            await save_ym_session(session, ym)
            task, claimed = await claim_yandex_assignment(
                session, u.id, u.gender or "male", ym.region or "", pid
            )
            if not task or not claimed:
                await clear_ym_session(session, u.id)
                await message.answer(
                    "Других заданий нет. Свободные тексты могут быть для другого пола "
                    "или с будущей датой публикации.",
                    reply_markup=user_main_kb(),
                )
                return
            ym.task_id = task.id
            ym.task_text_id = claimed.id
            ym.step = "org"
            await save_ym_session(session, ym)
            await _send_org_info(message, session_factory, task.id)
            return
        ym.step = "website"
        await save_ym_session(session, ym)
    await state.set_state(YandexMapsUserFSM.website)
    site_hint = (
        "Пришлите ссылку на официальный сайт компании (начинается с https://)."
    )
    no_site_hint = (
        "Если у организации нет сайта — пришлите ссылку на её страницу "
        "в соцсети или каталоге (тоже https://)."
    )
    await message.answer(
        f"🌐 <b>Сайт организации</b>\n\n{blockquote(site_hint)}\n\n{blockquote(no_site_hint)}",
        parse_mode="HTML",
        reply_markup=ym_website_kb(),
    )


@router.message(YandexMapsUserFSM.website, F.text, ActiveYandexFlowFilter())
async def ym_website(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    url = (message.text or "").strip()
    if url in {BTN_YM_YES, BTN_YM_NO}:
        await message.answer(
            "Сейчас нужна ссылка на <b>сайт организации</b> (https://…), а не «Да»/«Нет».",
            parse_mode="HTML",
            reply_markup=ym_website_kb(),
        )
        return
    if url == BTN_BACK_PLATFORMS:
        from handlers.user_handlers import _send_platform_list

        await state.clear()
        async with session_factory() as session:
            u = await ensure_user(
                session, message.from_user.id, message.from_user.username, referred_by_id=None
            )
            await reset_incomplete_ym_flow(session, u.id)
        await _send_platform_list(message, session_factory, state)
        return
    if len(url) < 8 or not url.startswith(("http://", "https://")):
        await message.answer(
            "Нужна ссылка на сайт организации: начинается с https://.",
            reply_markup=ym_website_kb(),
        )
        return
    data = await state.get_data()
    pid = data.get("ym_platform_id")
    await state.set_state(None)
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        ym = await get_active_ym_session(session, u.id)
        if not ym:
            return
        ym.website_url = url[:1024]
        ym.step = "quiz_intro"
        await save_ym_session(session, ym)
    if pid:
        await state.update_data(ym_platform_id=pid)
    await message.answer(
        f"🗺 <b>Контрольные вопросы</b>\n\n"
        f"{blockquote('Ответьте «Да» или «Нет» на каждый вопрос. Правильность не проверяется. '
                       f'Между показом вопроса и ответом — не менее {settings.yandex_answer_min_seconds} с, '
                       f'иначе блокировка на {settings.yandex_cheat_ban_days} дн.')}",
        parse_mode="HTML",
        reply_markup=ym_quiz_intro_kb(),
    )


@router.message(F.text == BTN_YM_REFUSE, ActiveYandexFlowFilter())
async def ym_quiz_refuse(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        ym = await get_active_ym_session(session, u.id)
        if ym and ym.task_text_id:
            from repo import release_task_text

            await release_task_text(session, u.id, int(ym.task_text_id))
        await clear_ym_session(session, u.id)
    await state.clear()
    await message.answer(
        "Вы отказались от задания.",
        reply_markup=user_main_kb(),
    )


@router.message(F.text == BTN_YM_START, ActiveYandexFlowFilter())
async def ym_quiz_start(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        ym = await get_active_ym_session(session, u.id)
        if not ym or ym.step != "quiz_intro" or not ym.task_id:
            return
        if not await task_platform_is_yandex(session, ym.task_id):
            return
        slots = await pick_random_quiz_slots(session, count=YANDEX_QUIZ_POOL_SIZE)
        if not slots:
            await message.answer(
                f"В пуле меньше {YANDEX_QUIZ_POOL_SIZE} активных вопросов. Обратитесь к администратору.",
            )
            return
        ym.quiz_slots = format_question_order(slots)
        ym.step = "question"
        ym.question_index = 0
        ym.question_shown_at = datetime.utcnow()
        await save_ym_session(session, ym)
        questions = await list_yandex_questions_for_ym_session(session, ym)
        if len(questions) < YANDEX_QUIZ_POOL_SIZE:
            await message.answer("Вопросы теста не настроены. Обратитесь к администратору.")
            return
        q = questions[0]
        total = len(questions)
    await state.set_state(YandexMapsUserFSM.quiz)
    await message.answer(
        f"<b>Вопрос 1 из {total}</b>\n\n{blockquote(q.body)}",
        parse_mode="HTML",
        reply_markup=ym_question_kb(),
    )


@router.message(F.text == BTN_YM_RESET, ActiveYandexFlowFilter())
async def ym_reset(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    data = await state.get_data()
    pid = int(data.get("ym_platform_id") or 0)
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        ym = await get_active_ym_session(session, u.id)
        if ym:
            if ym.task_text_id:
                await release_ym_assignment(session, u.id, int(ym.task_text_id))
        if not u.gender or not ym or not ym.region:
            await clear_ym_session(session, u.id)
            await message.answer("Нет данных для нового подбора.", reply_markup=user_main_kb())
            return
        ym.task_id = None
        ym.task_text_id = None
        ym.question_index = 0
        ym.quiz_slots = None
        ym.question_shown_at = None
        ym.step = "assign"
        task, claimed = await claim_yandex_assignment(
            session, u.id, u.gender, ym.region, pid
        )
        if not task or not claimed:
            await clear_ym_session(session, u.id)
            await message.answer("Нет свободных заданий.", reply_markup=user_main_kb())
            return
        ym.task_id = task.id
        ym.task_text_id = claimed.id
        ym.step = "org"
        await save_ym_session(session, ym)
    await _send_org_info(message, session_factory, task.id)


@router.message(
    YandexMapsUserFSM.quiz,
    F.text.in_({BTN_YM_Q_YES, BTN_YM_Q_NO}),
    ActiveYandexFlowFilter(),
)
async def ym_answer(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    async with session_factory() as session:
        u = await ensure_user(
            session, message.from_user.id, message.from_user.username, referred_by_id=None
        )
        ym = await get_active_ym_session(session, u.id)
        if not ym or ym.step != "question" or not ym.task_id:
            return
        if not await task_platform_is_yandex(session, ym.task_id):
            return
        if answer_is_too_fast(ym.question_shown_at, settings.yandex_answer_min_seconds):
            await _handle_quiz_cheat(
                message,
                session_factory,
                state,
                settings,
                user_id=u.id,
                ym=ym,
                min_seconds=settings.yandex_answer_min_seconds,
                ban_days=settings.yandex_cheat_ban_days,
            )
            return
        questions = await list_yandex_questions_for_ym_session(session, ym)
        if not questions:
            return
        nxt = ym.question_index + 1
        if nxt < len(questions):
            ym.question_index = nxt
            ym.question_shown_at = datetime.utcnow()
            await save_ym_session(session, ym)
            q = questions[nxt]
            await message.answer(
                f"<b>Вопрос {nxt + 1} из {len(questions)}</b>\n\n{blockquote(q.body)}",
                parse_mode="HTML",
                reply_markup=ym_question_kb(),
            )
            return
        freeze_min = settings.yandex_quiz_freeze_minutes
        ym.question_shown_at = None
        ym.step = "frozen"
        ym.freeze_until = datetime.utcnow() + timedelta(minutes=freeze_min)
        await save_ym_session(session, ym)
        t = await get_task(session, ym.task_id)
        reward = float(t.reward or 0) if t else 0.0
        freeze_label = format_quiz_freeze_duration(freeze_min)
    await state.set_state(None)
    await message.answer(
        f"✅ <b>Вы ответили на все вопросы</b>\n\n"
        f"{blockquote(f'Бот «заморожен» на {freeze_label}. '
                       f'После этого придёт текст отзыва отдельным сообщением.')}\n\n"
        f"Сумма <b>{reward:.2f} ₽</b> будет зачислена в баланс ожидания.",
        parse_mode="HTML",
        reply_markup=user_main_kb(),
    )


@router.message(F.text == BTN_BACK_PLATFORMS)
async def ym_back_platforms(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    state: FSMContext,
    settings: Settings,
):
    from handlers.user_handlers import _send_platform_list

    await _send_platform_list(message, session_factory, state)
