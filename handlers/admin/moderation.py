from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import Document, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import Submission, SubmissionStatus, User
from handlers.admin.common import is_admin
from handlers.admin.states import AdminImport
from handlers.formatting import blockquote, section
from handlers.keyboards import (
    A_IMPORT_EXCEL,
    admin_back_home_kb,
    admin_cancel_kb,
    admin_moderation_item_kb,
    parse_submission_action,
)
from repo import get_default_platform, import_review_texts, import_review_texts_to_task
from services.publish_scheduler import activate_due_texts
from services.rewards import approve_submission, reject_submission
from services.texts_import import parse_review_texts_excel

router = Router(name="admin_mod")


@router.message(F.text == A_IMPORT_EXCEL)
async def msg_import_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(AdminImport.waiting_file)
    await message.answer(
        f"📥 <b>Импорт из Excel</b>\n\n"
        f"{section('Файл', 'Пришлите .xlsx: Номер, Ссылка, Пол (М/Ж), Текст, Дата; опционально Заказчик, Оплата/Вознаграждение (₽).')}\n\n"
        f"{blockquote('Создаёт задания по ссылкам и тексты в пул. Публикация с 00:00 указанной даты. '
                       'Для одного заказчика удобнее: Заказчики → пул → Excel в пул.')}",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AdminImport.waiting_file, F.document)
async def adm_import_file(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    pool_tid = data.get("pool_task_id")
    doc: Document = message.document
    name = (doc.file_name or "").lower()
    if not name.endswith(".xlsx"):
        await message.answer("Нужен .xlsx", reply_markup=admin_cancel_kb())
        return
    file = await message.bot.get_file(doc.file_id)
    buf = await message.bot.download_file(file.file_path)
    raw = buf.read()
    items, errs = parse_review_texts_excel(raw, settings.app_timezone)
    if pool_tid:
        async with session_factory() as session:
            added, notes = await import_review_texts_to_task(session, int(pool_tid), items)
            await activate_due_texts(session)
        await state.clear()
        from handlers.admin.tasks_mgmt import send_pool_message

        lines = [f"Добавлено в пул: {added}."]
        if errs:
            lines.append("Ошибки:\n" + "\n".join(errs[:10]))
        if notes:
            lines.append("\n".join(notes[:15]))
        await message.answer("\n".join(lines), reply_markup=admin_back_home_kb())
        await send_pool_message(message, session_factory, int(pool_tid), settings)
        return
    if errs and not items:
        await message.answer("Ошибки:\n" + "\n".join(errs[:20]), reply_markup=admin_cancel_kb())
        return
    async with session_factory() as session:
        default_p = await get_default_platform(session)
        pid_default = default_p.id if default_p else 1
        texts_n, tasks_n, _ = await import_review_texts(session, items, pid_default)
        await activate_due_texts(session)
    await state.clear()
    extra = ""
    if errs:
        extra = "\n\n" + blockquote("\n".join(errs[:12]))
    await message.answer(
        f"✅ <b>Импорт завершён</b>\n\n"
        f"{section('Результат', f'Текстов: {texts_n}, новых заданий: {tasks_n}')}{extra}",
        parse_mode="HTML",
        reply_markup=admin_back_home_kb(),
    )


@router.message(F.text.func(lambda t: parse_submission_action(t) is not None))
async def msg_submission_action(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
):
    """Одобрить/отклонить — кнопки под карточками в «Задания на проверке»."""
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
    if not ok:
        await message.answer("Не удалось отклонить.", reply_markup=admin_back_home_kb())
        return
    await message.answer("Отклонено.", reply_markup=admin_back_home_kb())
    async with session_factory() as session:
        sub = await session.get(Submission, sid)
        if sub and sub.status == SubmissionStatus.REJECTED and sub.user:
            try:
                await message.bot.send_message(sub.user.telegram_id, "Отзыв не принят модератором.")
            except (TelegramForbiddenError, TelegramBadRequest):
                pass
