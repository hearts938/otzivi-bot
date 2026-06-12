from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from repo import (
    add_task_text,
    apply_user_balance_change,
    count_approved_submissions,
    create_platform,
    create_customer_task,
    create_task,
    delete_platform,
    delete_task,
    delete_task_text,
    delete_task_texts_by_numbers,
    get_default_platform,
    get_setting,
    get_task,
    get_user_by_id,
    get_support_ticket,
    list_open_support_tickets,
    count_open_support_tickets,
    count_submissions_in_cooldown,
    import_review_texts,
    list_pending_submissions_for_task,
    list_platforms_with_pending_reviews,
    list_tasks_with_pending_reviews,
    list_all_yandex_questions,
    update_yandex_question,
    list_all_tasks,
    list_platforms_all,
    list_users_admin,
    list_users_with_stats,
    resolve_user_ref,
    update_task_fields,
    set_setting,
    set_user_banned,
    update_platform_cooldown,
)
from services.broadcast import (
    attachment_from_upload,
    parse_external_button_url,
    read_upload_file,
    run_broadcast,
)
from services.rewards import approve_submission, reject_submission
from services.reviews_stock import (
    fetch_platform_review_stock,
    send_reviews_stock_to_admins,
)
from services.support_admin import deliver_support_reply, reject_support_ticket
from services.publish_scheduler import activate_due_texts
from services.gender import gender_label
from services.text_pool import build_pool_lines, parse_number_list
from services.texts_import import looks_like_xlsx, parse_review_texts_excel
from services.timezone_util import publish_at_midnight
from services.admin_stats import list_platforms, platform_snapshot, user_activity_bundle
from services.yandex_maps import YANDEX_QUIZ_POOL_SIZE
from sqlalchemy import select
from database.models import Platform, SupportTicketStatus, User

_SUPPORT_STATUS = {
    SupportTicketStatus.OPEN: "открыто",
    SupportTicketStatus.ANSWERED: "отвечено",
    SupportTicketStatus.REJECTED: "отклонено",
}

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def _need_admin(request: Request) -> RedirectResponse | None:
    if not request.session.get("admin"):
        return RedirectResponse("/login", status_code=302)
    return None


def _sf(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_post(request: Request):
    form = await request.form()
    pw = (form.get("password") or "").strip()
    settings = _settings(request)
    if not settings.web_admin_password:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "WEB_ADMIN_PASSWORD не задан в .env"},
            status_code=400,
        )
    if pw != settings.web_admin_password:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Неверный пароль"}, status_code=401
        )
    request.session["admin"] = True
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/users", response_class=HTMLResponse)
async def users_summary(request: Request):
    r = _need_admin(request)
    if r:
        return r
    rows: list[dict] = []
    async with _sf(request)() as session:
        for u, done in await list_users_with_stats(session, limit=400):
            rows.append(
                {
                    "username": f"@{u.username}" if u.username else "(нет)",
                    "tg": u.telegram_id,
                    "balance": u.balance,
                    "done": done,
                }
            )
    return templates.TemplateResponse("users.html", {"request": request, "rows": rows})


@router.get("/users/manage", response_class=HTMLResponse)
async def users_manage(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        users = await list_users_admin(session, limit=300)
    return templates.TemplateResponse("users_manage.html", {"request": request, "users": users})


@router.get("/users/manage/{uid}", response_class=HTMLResponse)
async def user_detail(request: Request, uid: int):
    r = _need_admin(request)
    if r:
        return r
    msg = request.query_params.get("msg")
    err = request.query_params.get("err")
    async with _sf(request)() as session:
        u = await get_user_by_id(session, uid)
        if not u:
            return HTMLResponse("Не найден", status_code=404)
        done = await count_approved_submissions(session, u.id)
        d_act, w_act, m_act = await user_activity_bundle(session, u.id)
        name = " ".join(x for x in [u.first_name or "", u.last_name or ""] if x).strip() or "—"
        un = f"@{u.username}" if u.username else "—"
        act = "заблокирован" if u.is_banned else "активен"
        balance = float(u.balance or 0)
        pending_balance = float(u.pending_balance or 0)
        banned = bool(u.is_banned)
        text = (
            f"tg id: {u.telegram_id}\n"
            f"username: {un}\n"
            f"имя: {name}\n"
            f"регистрация: {u.created_at}\n"
            f"баланс: {balance:.2f}\n"
            f"заработок с рефералов: {float(u.referral_earned_total or 0):.2f}\n"
            f"выполнено заданий: {done}\n"
            f"общий заработок (с заданий): {float(u.total_earned or 0):.2f}\n"
            f"активность (одобр.): сегодня {d_act}, неделя {w_act}, месяц {m_act}\n"
            f"статус: {act}"
        )
    return templates.TemplateResponse(
        "user_detail.html",
        {
            "request": request,
            "uid": uid,
            "text": text,
            "banned": banned,
            "balance": balance,
            "pending_balance": pending_balance,
            "msg": msg,
            "err": err,
        },
    )


@router.post("/users/manage/{uid}/balance")
async def user_balance(request: Request, uid: int):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    action = (form.get("action") or "credit").strip()
    credit = action != "debit"
    raw = (form.get("amount") or "").strip().replace(",", ".").replace("−", "-").replace("–", "-")
    if raw.startswith("+"):
        raw = raw[1:].strip()
    try:
        amount = float(raw)
    except ValueError:
        return RedirectResponse(
            f"/users/manage/{uid}?err={quote('Нужно число, например 100')}",
            status_code=303,
        )
    if amount <= 0:
        return RedirectResponse(
            f"/users/manage/{uid}?err={quote('Сумма должна быть больше нуля')}",
            status_code=303,
        )
    async with _sf(request)() as session:
        u2 = await apply_user_balance_change(session, uid, amount, credit=credit)
        if not u2:
            return RedirectResponse("/users/manage", status_code=303)
        op = "Начислено" if credit else "Списано"
        flash = f"{op} {amount:.2f} ₽. Новый баланс: {u2.balance:.2f} ₽"
    return RedirectResponse(f"/users/manage/{uid}?msg={quote(flash)}", status_code=303)


@router.post("/users/manage/{uid}/ban")
async def user_ban(request: Request, uid: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        u = await get_user_by_id(session, uid)
        if not u:
            return RedirectResponse("/users/manage", status_code=302)
        await set_user_banned(session, uid, not u.is_banned)
    return RedirectResponse(f"/users/manage/{uid}", status_code=302)


def _import_page(
    request: Request,
    settings: Settings,
    *,
    status_code: int = 200,
    **extra,
):
    return templates.TemplateResponse(
        "import_texts.html",
        {
            "request": request,
            "msg": None,
            "err": None,
            "warnings": None,
            "timezone": settings.app_timezone,
            **extra,
        },
        status_code=status_code,
    )


@router.get("/import", response_class=HTMLResponse)
async def import_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return _import_page(request, _settings(request))


@router.post("/import", response_class=HTMLResponse)
async def import_post(
    request: Request,
    file: UploadFile | None = File(default=None),
):
    r = _need_admin(request)
    if r:
        return r
    settings: Settings = _settings(request)
    if file is None or not hasattr(file, "read"):
        return _import_page(
            request,
            settings,
            err="Файл не получен. Выберите .xlsx и нажмите «Загрузить и импортировать».",
            status_code=400,
        )
    raw, filename, _mime = await read_upload_file(file)
    if not raw:
        return _import_page(request, settings, err="Файл пустой.", status_code=400)
    if not looks_like_xlsx(filename, raw):
        return _import_page(
            request,
            settings,
            err=(
                "Нужен файл Excel .xlsx (не старый .xls). "
                "В Excel: «Файл → Сохранить как → Книга Excel (.xlsx)»."
            ),
            status_code=400,
        )
    try:
        items, parse_errs = await asyncio.to_thread(
            parse_review_texts_excel, raw, settings.app_timezone
        )
    except Exception as exc:
        return _import_page(
            request,
            settings,
            err=f"Ошибка чтения файла: {exc}",
            status_code=400,
        )
    if parse_errs and not items:
        return _import_page(
            request,
            settings,
            err="Импорт не выполнен. Исправьте ошибки в файле.",
            warnings=parse_errs[:30],
            status_code=400,
        )
    try:
        async with _sf(request)() as session:
            default_p = await get_default_platform(session)
            pid_default = default_p.id if default_p else 1
            texts_n, tasks_n, _ = await import_review_texts(session, items, pid_default)
            activated = await activate_due_texts(session)
    except Exception as exc:
        return _import_page(
            request,
            settings,
            err=f"Ошибка записи в базу: {exc}",
            status_code=500,
        )
    msg = (
        f"Готово: загружено текстов — {texts_n}, "
        f"создано новых заданий (по ссылкам) — {tasks_n}."
    )
    if activated:
        msg += f" Сразу опубликовано по расписанию: {activated}."
    return _import_page(
        request,
        settings,
        msg=msg,
        warnings=parse_errs[:30] if parse_errs else None,
    )


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return templates.TemplateResponse("broadcast.html", {"request": request, "msg": None, "err": None})


@router.post("/broadcast", response_class=HTMLResponse)
async def broadcast_post(
    request: Request,
    text: str = Form(...),
    btn: str = Form("Старт"),
    attachment: UploadFile | None = File(default=None),
    photo: UploadFile | None = File(default=None),
):
    r = _need_admin(request)
    if r:
        return r
    text = (text or "").strip()
    btn = (btn or "Старт").strip()[:64]
    bot = request.app.state.bot
    me = await bot.get_me()
    if not me.username:
        return templates.TemplateResponse(
            "broadcast.html",
            {"request": request, "msg": None, "err": "У бота нет username"},
            status_code=400,
        )
    url = f"https://t.me/{me.username}?start=broadcast"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn, url=url)]])
    raw_upload = attachment if (attachment and attachment.filename) else photo
    file_bytes, file_name, file_mime = await read_upload_file(raw_upload)
    if raw_upload and not file_bytes:
        return templates.TemplateResponse(
            "broadcast.html",
            {
                "request": request,
                "msg": None,
                "err": "Файл не загрузился. Проверьте размер (до 10 МБ для фото) и попробуйте снова.",
            },
            status_code=400,
        )
    attachment_data = attachment_from_upload(
        file_bytes,
        filename=file_name,
        mime_type=file_mime,
    )
    async with _sf(request)() as session:
        rids = (await session.execute(select(User.telegram_id))).all()
    ids = [row[0] for row in rids]
    ok, bad = await run_broadcast(
        bot,
        ids,
        text=text,
        reply_markup=kb,
        attachment=attachment_data,
    )
    media = ""
    if attachment_data.kind == "photo_bytes":
        media = ", с фото"
    elif attachment_data.kind == "document_id":
        media = ", с файлом"
    msg = f"Успешно: {ok}, ошибок: {bad}{media}"
    return templates.TemplateResponse("broadcast.html", {"request": request, "msg": msg, "err": None})


@router.get("/reviews-stock", response_class=HTMLResponse)
async def reviews_stock_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    settings = _settings(request)
    async with _sf(request)() as session:
        stock = await fetch_platform_review_stock(session)
    total_free = sum(x.free_total for x in stock)
    report_time = (
        f"{settings.reviews_stock_report_hour:02d}:"
        f"{settings.reviews_stock_report_minute:02d}"
    )
    return templates.TemplateResponse(
        "reviews_stock.html",
        {
            "request": request,
            "rows": stock,
            "total_free": total_free,
            "timezone": settings.app_timezone,
            "report_time": report_time,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.post("/reviews-stock/send")
async def reviews_stock_send_now(request: Request):
    r = _need_admin(request)
    if r:
        return r
    settings = _settings(request)
    bot = request.app.state.bot
    if not settings.admin_ids:
        return RedirectResponse(
            "/reviews-stock?err=" + quote("ADMIN_IDS не задан в .env"),
            status_code=303,
        )
    ok, bad = await send_reviews_stock_to_admins(
        bot, request.app.state.session_factory, settings
    )
    return RedirectResponse(
        f"/reviews-stock?msg={quote(f'Отправлено: {ok}, ошибок: {bad}')}",
        status_code=303,
    )


@router.get("/broadcast-external", response_class=HTMLResponse)
async def broadcast_external_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return templates.TemplateResponse(
        "broadcast_external.html",
        {"request": request, "msg": None, "err": None},
    )


@router.post("/broadcast-external", response_class=HTMLResponse)
async def broadcast_external_post(
    request: Request,
    text: str = Form(...),
    btn: str = Form("Перейти"),
    url: str = Form(...),
    attachment: UploadFile | None = File(default=None),
):
    r = _need_admin(request)
    if r:
        return r
    text = (text or "").strip()
    btn = (btn or "Перейти").strip()[:64]
    link = parse_external_button_url(url)
    if not link:
        return templates.TemplateResponse(
            "broadcast_external.html",
            {
                "request": request,
                "msg": None,
                "err": "Нужна ссылка, начинающаяся с http:// или https://",
            },
            status_code=400,
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn, url=link)]])
    bot = request.app.state.bot
    file_bytes, file_name, file_mime = await read_upload_file(attachment)
    if attachment and attachment.filename and not file_bytes:
        return templates.TemplateResponse(
            "broadcast_external.html",
            {
                "request": request,
                "msg": None,
                "err": "Файл не загрузился. Проверьте размер и попробуйте снова.",
            },
            status_code=400,
        )
    attachment_data = attachment_from_upload(
        file_bytes,
        filename=file_name,
        mime_type=file_mime,
    )
    async with _sf(request)() as session:
        rids = (await session.execute(select(User.telegram_id))).all()
    ids = [row[0] for row in rids]
    ok, bad = await run_broadcast(
        bot,
        ids,
        text=text,
        reply_markup=kb,
        attachment=attachment_data,
    )
    media = ""
    if attachment_data.kind == "photo_bytes":
        media = ", с фото"
    elif attachment_data.kind == "document_id":
        media = ", с файлом"
    msg = f"Успешно: {ok}, ошибок: {bad}{media}"
    return templates.TemplateResponse(
        "broadcast_external.html",
        {"request": request, "msg": msg, "err": None},
    )


@router.get("/review", response_class=HTMLResponse)
async def review_root(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        platforms = await list_platforms_with_pending_reviews(session)
        cooldown = await count_submissions_in_cooldown(session)
    pending_total = sum(cnt for _, cnt in platforms)
    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "platforms": platforms,
            "pending_total": pending_total,
            "cooldown": cooldown,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.get("/review/platform/{platform_id}", response_class=HTMLResponse)
async def review_platform(request: Request, platform_id: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        platform = await session.get(Platform, platform_id)
        if not platform:
            return RedirectResponse("/review?err=" + quote("Сервис не найден"), status_code=303)
        tasks = await list_tasks_with_pending_reviews(session, platform_id)
        cooldown = await count_submissions_in_cooldown(session, platform_id=platform_id)
    pending_total = sum(cnt for _, cnt in tasks)
    return templates.TemplateResponse(
        "review_platform.html",
        {
            "request": request,
            "platform": platform,
            "tasks": tasks,
            "pending_total": pending_total,
            "cooldown": cooldown,
        },
    )


@router.get("/review/task/{task_id}", response_class=HTMLResponse)
async def review_task(request: Request, task_id: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        task = await get_task(session, task_id)
        if not task:
            return RedirectResponse("/review?err=" + quote("Задание не найдено"), status_code=303)
        subs = await list_pending_submissions_for_task(session, task_id)
        cooldown = await count_submissions_in_cooldown(session, task_id=task_id)
    rows = []
    for sub in subs:
        done = sub.completed_at or sub.created_at
        rows.append(
            {
                "id": sub.id,
                "user": sub.user,
                "gender_label": gender_label(sub.user.gender if sub.user else None),
                "review_text": sub.review_text or "",
                "done_at": done.strftime("%d.%m.%Y %H:%M") if done else "—",
            }
        )
    return templates.TemplateResponse(
        "review_task.html",
        {
            "request": request,
            "task": task,
            "submissions": rows,
            "cooldown": cooldown,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


async def _notify_review_decision(request: Request, user_tg_id: int, *, approved: bool) -> None:
    bot = request.app.state.bot
    text = (
        "✅ Отзыв одобрен, вознаграждение на балансе."
        if approved
        else "Отзыв не принят модератором."
    )
    try:
        await bot.send_message(user_tg_id, text)
    except (TelegramForbiddenError, TelegramBadRequest):
        pass


@router.post("/review/{submission_id}/approve")
async def review_approve(request: Request, submission_id: int):
    r = _need_admin(request)
    if r:
        return r
    settings = _settings(request)
    task_id: int | None = None
    user_tg: int | None = None
    info: str | None = None
    async with _sf(request)() as session:
        from database.models import Submission

        sub_before = await session.get(Submission, submission_id)
        task_id = sub_before.task_id if sub_before else None
        info = await approve_submission(session, settings, submission_id)
        if info:
            sub_after = await session.get(Submission, submission_id)
            if sub_after and sub_after.user_id:
                u = await session.get(User, sub_after.user_id)
                user_tg = u.telegram_id if u else None
    if not info or not task_id:
        return RedirectResponse(
            f"/review?err={quote('Не удалось одобрить')}",
            status_code=303,
        )
    if user_tg:
        await _notify_review_decision(request, user_tg, approved=True)
    return RedirectResponse(
        f"/review/task/{task_id}?msg={quote(info.replace(chr(10), ' '))}",
        status_code=303,
    )


@router.post("/review/{submission_id}/reject")
async def review_reject(request: Request, submission_id: int):
    r = _need_admin(request)
    if r:
        return r
    task_id: int | None = None
    user_tg: int | None = None
    ok = False
    async with _sf(request)() as session:
        from database.models import Submission

        sub_before = await session.get(Submission, submission_id)
        task_id = sub_before.task_id if sub_before else None
        if sub_before and sub_before.user_id:
            u = await session.get(User, sub_before.user_id)
            user_tg = u.telegram_id if u else None
        ok = await reject_submission(session, submission_id)
    if not ok or not task_id:
        return RedirectResponse(
            f"/review?err={quote('Не удалось отклонить')}",
            status_code=303,
        )
    if user_tg:
        await _notify_review_decision(request, user_tg, approved=False)
    return RedirectResponse(
        f"/review/task/{task_id}?msg={quote('Отклонено')}",
        status_code=303,
    )


@router.get("/finance", response_class=HTMLResponse)
async def finance_list(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        pls = await list_platforms(session)
    return templates.TemplateResponse("finance.html", {"request": request, "platforms": pls})


@router.get("/finance/{pid}", response_class=HTMLResponse)
async def finance_detail(request: Request, pid: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        snap = await platform_snapshot(session, pid)
    if not snap:
        return HTMLResponse("Нет данных", status_code=404)
    return templates.TemplateResponse(
        "finance_detail.html",
        {"request": request, "name": snap.platform.name, "snap": snap},
    )


@router.get("/balance", response_class=HTMLResponse)
async def balance_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return templates.TemplateResponse(
        "balance.html",
        {"request": request, "msg": None, "err": None, "ref": None, "action": "credit", "amount": None},
    )


@router.post("/balance", response_class=HTMLResponse)
async def balance_post(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    ref = (form.get("ref") or "").strip()
    action = (form.get("action") or "credit").strip()
    credit = action != "debit"
    raw = (form.get("amount") or "").strip().replace(",", ".").replace("−", "-").replace("–", "-")
    if raw.startswith("+"):
        raw = raw[1:].strip()
    try:
        amount = float(raw)
    except ValueError:
        return templates.TemplateResponse(
            "balance.html",
            {
                "request": request,
                "msg": None,
                "err": "Нужно число, например 100",
                "ref": ref,
                "action": action,
                "amount": form.get("amount"),
            },
            status_code=400,
        )
    if amount <= 0:
        return templates.TemplateResponse(
            "balance.html",
            {
                "request": request,
                "msg": None,
                "err": "Сумма должна быть больше нуля",
                "ref": ref,
                "action": action,
                "amount": form.get("amount"),
            },
            status_code=400,
        )
    msg: str | None = None
    err: str | None = None
    async with _sf(request)() as session:
        u = await resolve_user_ref(session, ref)
        if not u:
            err = "Пользователь не найден"
        else:
            u2 = await apply_user_balance_change(session, u.id, amount, credit=credit)
            op = "Начислено" if credit else "Списано"
            pending = float(u2.pending_balance or 0)
            msg = (
                f"{op} {amount:.2f} ₽ пользователю {u2.telegram_id}. "
                f"Баланс к выплате: {u2.balance:.2f} ₽, в ожидании: {pending:.2f} ₽"
            )
    return templates.TemplateResponse(
        "balance.html",
        {
            "request": request,
            "msg": msg,
            "err": err,
            "ref": ref,
            "action": action,
            "amount": None if msg else form.get("amount"),
        },
        status_code=400 if err else 200,
    )


@router.get("/yandex-quiz", response_class=HTMLResponse)
async def yandex_quiz_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        questions = await list_all_yandex_questions(session)
    active_count = sum(1 for q in questions if q.active)
    return templates.TemplateResponse(
        "yandex_quiz.html",
        {
            "request": request,
            "pool_size": YANDEX_QUIZ_POOL_SIZE,
            "active_count": active_count,
            "questions": questions,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.get("/yandex-quiz/{slot}", response_class=HTMLResponse)
async def yandex_quiz_edit_get(request: Request, slot: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        rows = {q.slot: q for q in await list_all_yandex_questions(session)}
        q = rows.get(slot)
    if not q:
        return RedirectResponse("/yandex-quiz?err=" + quote("Слот не найден"), status_code=303)
    return templates.TemplateResponse(
        "yandex_quiz_edit.html",
        {
            "request": request,
            "slot": slot,
            "body": q.body,
            "active": q.active,
            "err": None,
        },
    )


@router.post("/yandex-quiz/{slot}")
async def yandex_quiz_edit_post(request: Request, slot: int):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    body = (form.get("body") or "").strip()
    active = form.get("active") == "1"
    if not body:
        return templates.TemplateResponse(
            "yandex_quiz_edit.html",
            {
                "request": request,
                "slot": slot,
                "body": body,
                "active": active,
                "err": "Текст не может быть пустым",
            },
            status_code=400,
        )
    async with _sf(request)() as session:
        q = await update_yandex_question(session, slot, body=body, active=active)
    if not q:
        return RedirectResponse("/yandex-quiz?err=" + quote("Слот не найден"), status_code=303)
    return RedirectResponse(f"/yandex-quiz?msg={quote(f'Слот {slot} обновлён')}", status_code=303)


@router.get("/stars", response_class=HTMLResponse)
async def stars_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        cur = await get_setting(session, "stars_rub_per_star", "1.0")
    return templates.TemplateResponse(
        "form_simple.html",
        {
            "request": request,
            "title": f"Курс звёзд (сейчас 1★ = {cur} ₽)",
            "action": "/stars",
            "submit": "Сохранить",
            "fields": [{"label": "Руб / звезда", "name": "rate", "type": "text", "value": cur}],
            "msg": None,
            "err": None,
        },
    )


@router.post("/stars", response_class=HTMLResponse)
async def stars_post(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    err: str | None = None
    v: float | None = None
    try:
        v = float(str(form.get("rate")).replace(",", "."))
    except Exception:
        err = "Нужно число"
    if v is not None and v <= 0:
        err = "Должно быть > 0"
        v = None
    if v is None:
        async with _sf(request)() as session:
            cur = await get_setting(session, "stars_rub_per_star", "1.0")
        return templates.TemplateResponse(
            "form_simple.html",
            {
                "request": request,
                "title": f"Курс звёзд (сейчас 1★ = {cur} ₽)",
                "action": "/stars",
                "submit": "Сохранить",
                "fields": [{"label": "Руб / звезда", "name": "rate", "type": "text", "value": str(form.get("rate") or "")}],
                "msg": None,
                "err": err or "Ошибка",
            },
            status_code=400,
        )
    async with _sf(request)() as session:
        await set_setting(session, "stars_rub_per_star", str(v))
    return RedirectResponse("/stars", status_code=302)


@router.get("/support", response_class=HTMLResponse)
async def support_list(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        tickets = await list_open_support_tickets(session)
        open_count = await count_open_support_tickets(session)
    return templates.TemplateResponse(
        "support.html",
        {
            "request": request,
            "tickets": tickets,
            "open_count": open_count,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.get("/support/{ticket_id}", response_class=HTMLResponse)
async def support_detail(request: Request, ticket_id: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        ticket = await get_support_ticket(session, ticket_id, with_user=True)
        if not ticket or not ticket.user:
            return RedirectResponse("/support?err=" + quote("Обращение не найдено"), status_code=303)
        user = ticket.user
        status_label = _SUPPORT_STATUS.get(ticket.status, ticket.status)
    return templates.TemplateResponse(
        "support_detail.html",
        {
            "request": request,
            "ticket": ticket,
            "user": user,
            "status_label": status_label,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.post("/support/{ticket_id}/reply")
async def support_reply(
    request: Request,
    ticket_id: int,
    reply: str = Form(...),
    photo: UploadFile | None = File(default=None),
):
    r = _need_admin(request)
    if r:
        return r
    photo_bytes, photo_name, _ = await read_upload_file(photo)
    bot = request.app.state.bot
    async with _sf(request)() as session:
        ok, err = await deliver_support_reply(
            bot,
            session,
            ticket_id,
            text=reply,
            photo_bytes=photo_bytes or None,
            photo_filename=photo_name or "photo.jpg",
        )
    if not ok:
        return RedirectResponse(
            f"/support/{ticket_id}?err={quote(err or 'Ошибка отправки')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/support?msg={quote(f'Ответ отправлен (sup{ticket_id})')}",
        status_code=303,
    )


@router.post("/support/{ticket_id}/reject")
async def support_reject(request: Request, ticket_id: int):
    r = _need_admin(request)
    if r:
        return r
    bot = request.app.state.bot
    async with _sf(request)() as session:
        ok, err = await reject_support_ticket(bot, session, ticket_id)
    if not ok:
        return RedirectResponse(
            f"/support/{ticket_id}?err={quote(err or 'Ошибка')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/support?msg={quote(f'Обращение sup{ticket_id} отклонено')}",
        status_code=303,
    )


@router.get("/outreach", response_class=HTMLResponse)
async def outreach_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return templates.TemplateResponse(
        "form_simple.html",
        {
            "request": request,
            "title": "Обращение от бота",
            "action": "/outreach",
            "submit": "Отправить",
            "fields": [
                {"label": "Кому (@username / tg id)", "name": "ref", "type": "text"},
                {"label": "Текст", "name": "text", "type": "text"},
            ],
            "msg": None,
            "err": None,
        },
    )


@router.post("/outreach", response_class=HTMLResponse)
async def outreach_post(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    ref = (form.get("ref") or "").strip()
    txt = (form.get("text") or "").strip()[:3500]
    bot = request.app.state.bot
    async with _sf(request)() as session:
        u = await resolve_user_ref(session, ref)
        if not u:
            return templates.TemplateResponse(
                "form_simple.html",
                {
                    "request": request,
                    "title": "Обращение",
                    "action": "/outreach",
                    "submit": "Отправить",
                    "fields": [
                        {"label": "Кому", "name": "ref", "type": "text", "value": ref},
                        {"label": "Текст", "name": "text", "type": "text"},
                    ],
                    "msg": None,
                    "err": "Не найден",
                },
                status_code=400,
            )
        try:
            await bot.send_message(u.telegram_id, txt)
            msg = "Отправлено"
            err = None
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            msg = None
            err = str(e)
    return templates.TemplateResponse(
        "form_simple.html",
        {
            "request": request,
            "title": "Обращение",
            "action": "/outreach",
            "submit": "Отправить",
            "fields": [
                {"label": "Кому", "name": "ref", "type": "text"},
                {"label": "Текст", "name": "text", "type": "text"},
            ],
            "msg": msg,
            "err": err,
        },
        status_code=400 if err else 200,
    )


@router.get("/platforms", response_class=HTMLResponse)
async def platforms_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        pls = await list_platforms_all(session)
    return templates.TemplateResponse("platforms.html", {"request": request, "platforms": pls})


@router.post("/platforms/add")
async def platforms_add(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    name = (form.get("name") or "").strip()
    slug = (form.get("slug") or "").strip()
    try:
        cd = int(form.get("cd") or 0)
    except ValueError:
        cd = 0
    async with _sf(request)() as session:
        await create_platform(session, name, slug, cd)
    return RedirectResponse("/platforms", status_code=302)


@router.post("/platforms/{pid}/cd")
async def platforms_cd(request: Request, pid: int):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    try:
        s = int(form.get("seconds") or 0)
    except ValueError:
        s = 0
    async with _sf(request)() as session:
        await update_platform_cooldown(session, pid, s)
    return RedirectResponse("/platforms", status_code=302)


@router.post("/platforms/{pid}/delete")
async def platforms_del(request: Request, pid: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        d = await get_default_platform(session)
        def_id = d.id if d else 1
        await delete_platform(session, pid, def_id)
    return RedirectResponse("/platforms", status_code=302)


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        tasks = await list_all_tasks(session)
        pls = await list_platforms_all(session)
    return templates.TemplateResponse("tasks.html", {"request": request, "tasks": tasks, "platforms": pls})


@router.post("/tasks/add")
async def tasks_add(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    try:
        pid = int(form.get("platform_id") or 0)
    except ValueError:
        pid = 0
    name = (form.get("customer_name") or "").strip()
    link = (form.get("link") or "").strip()
    region = (form.get("region") or "").strip()
    org_address = (form.get("org_address") or "").strip()
    try:
        rw = float(str(form.get("reward")).replace(",", "."))
    except Exception:
        rw = 0.0
    async with _sf(request)() as session:
        pls = await list_platforms_all(session)
        t, err = await create_customer_task(
            session,
            name,
            link,
            pid,
            rw,
            "",
            org_address=org_address or None,
            region=region or None,
        )
    if err:
        async with _sf(request)() as session:
            tasks = await list_all_tasks(session)
        return templates.TemplateResponse(
            "tasks.html",
            {"request": request, "tasks": tasks, "platforms": pls, "err": err},
            status_code=400,
        )
    return RedirectResponse(f"/tasks/{t.id}", status_code=302)


def _pool_view(task, lines):
    active, waiting, taken = [], [], []
    for ln in lines:
        row = {
            "number": ln.number,
            "gender_label": gender_label(ln.gender) if ln.gender else "—",
            "preview": (ln.body[:140] + "…") if len(ln.body) > 140 else ln.body,
            "status_label": ln.status_label,
        }
        if ln.status == "active":
            active.append(row)
        elif ln.status == "waiting":
            waiting.append(row)
        else:
            taken.append(row)
    return active, waiting, taken


@router.get("/tasks/{tid}", response_class=HTMLResponse)
async def task_detail(request: Request, tid: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        t = await get_task(session, tid)
    if not t:
        return HTMLResponse("Нет", status_code=404)
    lines = build_pool_lines(t.texts or [])
    active, waiting, taken = _pool_view(t, lines)
    qp = request.query_params
    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            "task": t,
            "active": active,
            "waiting": waiting,
            "taken": taken,
            "msg": qp.get("msg"),
            "err": qp.get("err"),
        },
    )


@router.post("/tasks/{tid}/meta")
async def task_meta_update(request: Request, tid: int):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    region = (form.get("region") or "").strip()
    org_address = (form.get("org_address") or "").strip()
    async with _sf(request)() as session:
        t = await update_task_fields(
            session,
            tid,
            region=region,
            org_address=org_address,
        )
    if not t:
        return RedirectResponse("/tasks?err=" + quote("Заказчик не найден"), status_code=303)
    return RedirectResponse(f"/tasks/{tid}?msg={quote('Сохранено')}", status_code=303)


@router.post("/tasks/{tid}/reward")
async def task_reward_update(request: Request, tid: int):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    try:
        rw = float(str(form.get("reward", "0")).replace(",", ".").strip())
    except Exception:
        return RedirectResponse(f"/tasks/{tid}?err=Неверная+сумма", status_code=302)
    if rw < 0:
        return RedirectResponse(f"/tasks/{tid}?err=Сумма+не+может+быть+отрицательной", status_code=302)
    async with _sf(request)() as session:
        t = await update_task_fields(session, tid, reward=rw)
    if not t:
        return RedirectResponse("/tasks?err=Заказчик+не+найден", status_code=302)
    return RedirectResponse(
        f"/tasks/{tid}?msg=Оплата+обновлена:+{rw:.2f}+₽",
        status_code=302,
    )


@router.post("/tasks/{tid}/texts")
async def task_text_add(request: Request, tid: int):
    r = _need_admin(request)
    if r:
        return r
    settings = _settings(request)
    form = await request.form()
    body = (form.get("body") or "").strip()
    gender = (form.get("gender") or "male").strip()
    pub_raw = (form.get("publish_date") or "сейчас").strip().lower()
    publish_at = None
    published = True
    if pub_raw not in ("сейчас", "now", "-", ""):
        try:
            d = pd.to_datetime(pub_raw, dayfirst=True).date()
            publish_at = publish_at_midnight(d, settings.app_timezone)
            published = publish_at <= datetime.utcnow()
        except Exception:
            return RedirectResponse(f"/tasks/{tid}?err=Неверная+дата", status_code=302)
    async with _sf(request)() as session:
        tt = await add_task_text(
            session,
            tid,
            body,
            required_gender=gender,
            publish_at=publish_at,
            published=published,
        )
        msg = f"Добавлен текст №{tt.text_number}"
    return RedirectResponse(f"/tasks/{tid}?msg={quote(msg)}", status_code=302)


@router.post("/tasks/{tid}/texts/delete")
async def task_texts_delete_bulk(request: Request, tid: int):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    nums = parse_number_list(form.get("numbers") or "")
    async with _sf(request)() as session:
        deleted, notes = await delete_task_texts_by_numbers(session, tid, nums)
    msg = f"Удалено: {deleted}"
    if notes:
        msg += ". " + "; ".join(notes[:5])
    return RedirectResponse(f"/tasks/{tid}?msg={quote(msg)}", status_code=302)


@router.post("/tasks/texts/{txid}/delete")
async def task_text_del(request: Request, txid: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        await delete_task_text(session, txid)
    return RedirectResponse(request.headers.get("referer") or "/tasks", status_code=302)


@router.post("/tasks/{tid}/delete")
async def task_del(request: Request, tid: int):
    r = _need_admin(request)
    if r:
        return r
    async with _sf(request)() as session:
        await delete_task(session, tid)
    return RedirectResponse("/tasks", status_code=302)
