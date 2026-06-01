from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from repo import (
    add_task_text,
    adjust_user_balance,
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
    import_review_texts,
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
from services.publish_scheduler import activate_due_texts
from services.gender import gender_label
from services.text_pool import build_pool_lines, parse_number_list
from services.texts_import import parse_review_texts_excel
from services.timezone_util import publish_at_midnight
from services.admin_stats import list_platforms, platform_snapshot, user_activity_bundle
from sqlalchemy import select
from database.models import User

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
    async with _sf(request)() as session:
        u = await get_user_by_id(session, uid)
        if not u:
            return HTMLResponse("Не найден", status_code=404)
        done = await count_approved_submissions(session, u.id)
        d_act, w_act, m_act = await user_activity_bundle(session, u.id)
    name = " ".join(x for x in [u.first_name or "", u.last_name or ""] if x).strip() or "—"
    un = f"@{u.username}" if u.username else "—"
    act = "заблокирован" if u.is_banned else "активен"
    text = (
        f"tg id: {u.telegram_id}\n"
        f"username: {un}\n"
        f"имя: {name}\n"
        f"регистрация: {u.created_at}\n"
        f"баланс: {u.balance:.2f}\n"
        f"заработок с рефералов: {u.referral_earned_total:.2f}\n"
        f"выполнено заданий: {done}\n"
        f"общий заработок (с заданий): {u.total_earned:.2f}\n"
        f"активность (одобр.): сегодня {d_act}, неделя {w_act}, месяц {m_act}\n"
        f"статус: {act}"
    )
    return templates.TemplateResponse(
        "user_detail.html",
        {"request": request, "uid": uid, "text": text, "banned": u.is_banned},
    )


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


@router.get("/import", response_class=HTMLResponse)
async def import_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    settings: Settings = _settings(request)
    return templates.TemplateResponse(
        "import_texts.html",
        {
            "request": request,
            "msg": None,
            "err": None,
            "warnings": None,
            "timezone": settings.app_timezone,
        },
    )


@router.post("/import", response_class=HTMLResponse)
async def import_post(request: Request):
    r = _need_admin(request)
    if r:
        return r
    settings: Settings = _settings(request)
    form = await request.form()
    raw_file = form.get("file")
    if not isinstance(raw_file, UploadFile) or not raw_file.filename:
        return templates.TemplateResponse(
            "import_texts.html",
            {
                "request": request,
                "msg": None,
                "err": "Выберите файл .xlsx",
                "warnings": None,
                "timezone": settings.app_timezone,
            },
            status_code=400,
        )
    name = raw_file.filename.lower()
    if not name.endswith(".xlsx"):
        return templates.TemplateResponse(
            "import_texts.html",
            {
                "request": request,
                "msg": None,
                "err": "Нужен файл в формате .xlsx",
                "warnings": None,
                "timezone": settings.app_timezone,
            },
            status_code=400,
        )
    raw = await raw_file.read()
    if not raw:
        return templates.TemplateResponse(
            "import_texts.html",
            {
                "request": request,
                "msg": None,
                "err": "Файл пустой.",
                "warnings": None,
                "timezone": settings.app_timezone,
            },
            status_code=400,
        )
    items, parse_errs = parse_review_texts_excel(raw, settings.app_timezone)
    if parse_errs and not items:
        return templates.TemplateResponse(
            "import_texts.html",
            {
                "request": request,
                "msg": None,
                "err": "Импорт не выполнен. Исправьте ошибки в файле.",
                "warnings": parse_errs[:30],
                "timezone": settings.app_timezone,
            },
            status_code=400,
        )
    async with _sf(request)() as session:
        default_p = await get_default_platform(session)
        pid_default = default_p.id if default_p else 1
        texts_n, tasks_n, _ = await import_review_texts(session, items, pid_default)
        activated = await activate_due_texts(session)
    msg = (
        f"Готово: загружено текстов — {texts_n}, "
        f"создано новых заданий (по ссылкам) — {tasks_n}."
    )
    if activated:
        msg += f" Сразу опубликовано по расписанию: {activated}."
    return templates.TemplateResponse(
        "import_texts.html",
        {
            "request": request,
            "msg": msg,
            "err": None,
            "warnings": parse_errs[:30] if parse_errs else None,
            "timezone": settings.app_timezone,
        },
    )


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_get(request: Request):
    r = _need_admin(request)
    if r:
        return r
    return templates.TemplateResponse("broadcast.html", {"request": request, "msg": None, "err": None})


@router.post("/broadcast", response_class=HTMLResponse)
async def broadcast_post(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    text = (form.get("text") or "").strip()
    btn = (form.get("btn") or "Старт").strip()[:64]
    raw_photo = form.get("photo")
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
    photo_bytes: bytes | None = None
    if isinstance(raw_photo, UploadFile) and raw_photo.filename:
        photo_bytes = await raw_photo.read()
    async with _sf(request)() as session:
        rids = (await session.execute(select(User.telegram_id))).all()
    ids = [row[0] for row in rids]
    ok = bad = 0
    for tid in ids:
        try:
            if photo_bytes:
                await bot.send_photo(
                    tid,
                    BufferedInputFile(photo_bytes, filename="cast.jpg"),
                    caption=text[:1024],
                    reply_markup=kb,
                )
            else:
                await bot.send_message(tid, text[:3500], reply_markup=kb)
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            bad += 1
        await asyncio.sleep(0.05)
    msg = f"Успешно: {ok}, ошибок: {bad}"
    return templates.TemplateResponse("broadcast.html", {"request": request, "msg": msg, "err": None})


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
        "form_simple.html",
        {
            "request": request,
            "title": "Баланс",
            "action": "/balance",
            "submit": "Применить",
            "fields": [
                {"label": "Пользователь (@username или tg id)", "name": "ref", "type": "text"},
                {"label": "Изменение (+/- число)", "name": "amount", "type": "text"},
            ],
            "msg": None,
            "err": None,
        },
    )


@router.post("/balance", response_class=HTMLResponse)
async def balance_post(request: Request):
    r = _need_admin(request)
    if r:
        return r
    form = await request.form()
    ref = (form.get("ref") or "").strip()
    try:
        delta = float(str(form.get("amount")).replace(",", "."))
    except Exception:
        return templates.TemplateResponse(
            "form_simple.html",
            {
                "request": request,
                "title": "Баланс",
                "action": "/balance",
                "submit": "Применить",
                "fields": [
                    {"label": "Пользователь", "name": "ref", "type": "text", "value": ref},
                    {"label": "Изменение", "name": "amount", "type": "text"},
                ],
                "msg": None,
                "err": "Нужно число",
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
            u2 = await adjust_user_balance(session, u.id, delta)
            msg = f"Новый баланс {u2.telegram_id}: {u2.balance:.2f}"
    return templates.TemplateResponse(
        "form_simple.html",
        {
            "request": request,
            "title": "Баланс",
            "action": "/balance",
            "submit": "Применить",
            "fields": [
                {"label": "Пользователь", "name": "ref", "type": "text", "value": ref},
                {"label": "Изменение", "name": "amount", "type": "text"},
            ],
            "msg": msg,
            "err": err,
        },
        status_code=400 if err else 200,
    )


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
