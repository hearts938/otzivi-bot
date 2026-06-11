from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import User
from handlers.admin.common import is_admin
from handlers.admin.states import BroadcastFSM
from handlers.formatting import blockquote
from handlers.keyboards import A_BROADCAST, admin_cancel_kb, admin_root_kb
from services.broadcast import resolve_telegram_attachment, run_broadcast

router = Router(name="admin_broadcast")


@router.message(F.text == A_BROADCAST)
async def br_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(BroadcastFSM.text)
    await message.answer(
        f"📣 <b>Рассылка</b>\n\n{blockquote('Введите текст сообщения для всех пользователей.')}",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(BroadcastFSM.text, F.text)
async def br_text(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(text=message.text or "")
    await state.set_state(BroadcastFSM.button)
    await message.answer("Текст кнопки под сообщением (например «Старт»):", reply_markup=admin_cancel_kb())


@router.message(BroadcastFSM.button, F.text)
async def br_btn(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(btn=(message.text or "Старт").strip()[:64])
    await state.set_state(BroadcastFSM.photo)
    await message.answer(
        "Пришлите фото или файл (картинки уйдут как фото, не как файл).\n"
        "Или напишите «нет».",
        reply_markup=admin_cancel_kb(),
    )


@router.message(BroadcastFSM.photo, F.text)
async def br_attachment_skip(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    if (message.text or "").strip().lower() not in ("нет", "no", "-"):
        await message.answer(
            "Пришлите фото/файл или напишите «нет».",
            reply_markup=admin_cancel_kb(),
        )
        return
    data = await state.get_data()
    await state.clear()
    await _run_broadcast(message, session_factory, data.get("text", ""), data.get("btn", "Старт"), None, None)


@router.message(BroadcastFSM.photo, F.photo)
async def br_attachment_photo(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    await _run_broadcast(
        message,
        session_factory,
        data.get("text", ""),
        data.get("btn", "Старт"),
        photo_file_id=message.photo[-1].file_id,
        document=None,
    )


@router.message(BroadcastFSM.photo, F.document)
async def br_attachment_document(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    await _run_broadcast(
        message,
        session_factory,
        data.get("text", ""),
        data.get("btn", "Старт"),
        photo_file_id=None,
        document=message.document,
    )


async def _run_broadcast(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    text: str,
    btn: str,
    photo_file_id: str | None,
    document,
) -> None:
    me = await message.bot.get_me()
    if not me.username:
        await message.answer("У бота нет username.", reply_markup=admin_root_kb())
        return
    url = f"https://t.me/{me.username}?start=broadcast"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn, url=url)]])
    attachment = await resolve_telegram_attachment(
        message.bot,
        photo_file_id=photo_file_id,
        document_file_id=document.file_id if document else None,
        document_mime=document.mime_type if document else None,
        document_filename=document.file_name if document else None,
    )
    async with session_factory() as session:
        r = await session.execute(select(User.telegram_id))
        ids = [row[0] for row in r.all()]
    await message.answer(f"Рассылка на {len(ids)} получателей…", reply_markup=admin_root_kb())
    ok, bad = await run_broadcast(
        message.bot,
        ids,
        text=text,
        reply_markup=kb,
        attachment=attachment,
    )
    await message.answer(f"Готово. Успешно: {ok}, ошибок: {bad}.", reply_markup=admin_root_kb())
