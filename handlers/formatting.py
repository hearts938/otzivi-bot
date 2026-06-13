"""Тексты сообщений с цитатами (blockquote) и данными пользователя."""

from __future__ import annotations

from html import escape as html_escape

from aiogram.types import User as TgUser

from database.models import SupportTicket, User
from services.gender import gender_label
from services.reward_input import format_reward_rub


def esc_html(text: object) -> str:
    return html_escape(str(text or ""), quote=False)


def blockquote(body: str) -> str:
    """Цитата только для обычного текста (HTML будет экранирован)."""
    body = esc_html((body or "—").strip())
    return f"<blockquote>{body}</blockquote>"


def blockquote_rich(body: str) -> str:
    """Цитата с HTML-разметкой (пользовательские поля — через esc_html)."""
    return f"<blockquote>{(body or '').strip()}</blockquote>"


def section(title: str, body: str) -> str:
    """Секция только для обычного текста в теле (HTML будет экранирован)."""
    return f"<b>{esc_html(title)}</b>\n{blockquote(body)}"


def section_rich(title: str, body: str) -> str:
    """Секция с HTML в теле (пользовательские поля — через esc_html)."""
    return f"<b>{esc_html(title)}</b>\n{blockquote_rich(body)}"


def tg_peer_lines(tg: TgUser) -> str:
    un = esc_html(f"@{tg.username}" if tg.username else "—")
    name = esc_html(
        " ".join(x for x in [tg.first_name or "", tg.last_name or ""] if x).strip() or "—"
    )
    return (
        f"Telegram ID: <code>{tg.id}</code>\n"
        f"Username: {un}\n"
        f"Имя в Telegram: {name}"
    )


def account_status_label(u: User) -> str:
    return "🚫 Заблокирован" if u.is_banned else "✅ Активен"


def db_user_lines(u: User) -> str:
    un = esc_html(f"@{u.username}" if u.username else "—")
    name = esc_html(
        " ".join(x for x in [u.first_name or "", u.last_name or ""] if x).strip() or "—"
    )
    platform_name = esc_html(u.platform_account_name or "—")
    ref_code = esc_html(u.referral_code)
    return (
        f"ID в базе: <code>{u.id}</code>\n"
        f"Telegram ID: <code>{u.telegram_id}</code>\n"
        f"Username: {un}\n"
        f"Имя: {name}\n"
        f"Пол: {gender_label(u.gender)}\n"
        f"Ник на площадках: {platform_name}\n"
        f"Реф. код: <code>{ref_code}</code>"
    )


def main_menu_text(u: User, ref_link: str) -> str:
    account_body = f"{db_user_lines(u)}\n\nСтатус: <b>{account_status_label(u)}</b>"
    return (
        f"🏠 <b>Главное меню</b>\n\n"
        f"{section_rich('Ваш аккаунт', account_body)}\n\n"
        f"{section('Реферальная ссылка', ref_link)}"
    )


def _referral_stats_block(referred_count: int, earned_from_referrals: float) -> str:
    return (
        f"Перешли по вашей ссылке: <b>{referred_count}</b>\n"
        f"Заработано с рефералов: <b>{earned_from_referrals:.2f}</b>"
    )


def referral_level_percent(
    referred_count: int,
    *,
    percent_up_to: float,
    percent_after: float,
    count_threshold: int,
) -> float:
    if referred_count <= count_threshold:
        return percent_up_to
    return percent_after


def _reviews_channel_line(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("http"):
        safe = esc_html(u)
        return f'<a href="{safe}">канал с отзывами</a>'
    handle = u.lstrip("@")
    label = esc_html(u if u.startswith("@") else f"@{u}")
    safe_handle = esc_html(handle)
    return f'<a href="https://t.me/{safe_handle}">{label}</a>'


def task_link_html(link: str | None) -> str:
    raw = (link or "").strip()
    if not raw:
        return "—"
    safe = esc_html(raw)
    return f'<a href="{safe}">{safe}</a>'


def profile_text(
    u: User,
    *,
    referred_count: int = 0,
    completed_tasks: int = 0,
    reviews_channel_url: str = "",
    percent_up_to: float = 20,
    percent_after: float = 5,
    count_threshold: int = 10,
) -> str:
    un = esc_html(f"@{u.username}" if u.username else "—")
    level_pct = referral_level_percent(
        referred_count,
        percent_up_to=percent_up_to,
        percent_after=percent_after,
        count_threshold=count_threshold,
    )
    lines = [
        f"Username в Telegram: <b>{un}</b>",
        f"Баланс к выплате: <b>{u.balance:.2f}</b> ₽",
        f"В ожидании: <b>{float(u.pending_balance or 0):.2f}</b> ₽",
        f"Выполнено заданий: <b>{completed_tasks}</b>",
        f"Общий заработок: <b>{u.total_earned:.2f}</b> ₽",
        f"Реферальный уровень: <b>{level_pct:.0f}%</b>",
        f"Заработано на рефералах: <b>{u.referral_earned_total:.2f}</b> ₽ "
        f"(уже входит в баланс)",
        f"Количество рефералов: <b>{referred_count}</b>",
    ]
    channel = _reviews_channel_line(reviews_channel_url)
    if channel:
        lines.append(f"Канал с отзывами: {channel}")
    return f"👤 <b>Личный кабинет</b>\n\n{blockquote_rich(chr(10).join(lines))}"


def withdraw_hint_text() -> str:
    return (
        f"💸 <b>Вывод средств</b>\n\n"
        f"{blockquote(
            'Оформите заявку через «Поддержку»: укажите сумму вывода и реквизиты. '
            'Минимальная сумма и сроки обработки — у администратора.'
        )}"
    )


def referral_text(
    u: User,
    link: str,
    referred_count: int = 0,
    *,
    percent_up_to: float = 20,
    percent_after: float = 5,
    count_threshold: int = 10,
) -> str:
    your_tier = (
        f"{percent_up_to:.0f}%"
        if referred_count <= count_threshold
        else f"{percent_after:.0f}%"
    )
    how = (
        f"Приглашённый переходит по ссылке и проходит опрос.\n"
        f"После одобрения его отзыва вам начисляется процент от его заработка:\n"
        f"· приглашённых <b>до {count_threshold}</b> — <b>{percent_up_to:.0f}%</b>\n"
        f"· приглашённых <b>больше {count_threshold}</b> — <b>{percent_after:.0f}%</b>\n\n"
        f"У вас сейчас <b>{referred_count}</b> приглашённых — ваша ставка: <b>{your_tier}</b>."
    )
    return (
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"{section_rich('Статистика', _referral_stats_block(referred_count, u.referral_earned_total))}\n\n"
        f"{section_rich('Как это работает', how)}\n\n"
        f"{section('Ссылка для приглашения', link)}"
    )


TASKS_MENU_RULES = (
    "· Не отменять задание, если отзыв уже оставлен\n"
    "· На выполнение даётся 60 минут\n"
    "· Вознаграждение выплачивается только после публикации отзыва в общий доступ\n"
    "· Краткая инструкция прилагается к каждому заданию"
)


def tasks_menu_entry_text(platform_count: int, *, claim_minutes: int = 60) -> str:
    rules = TASKS_MENU_RULES.replace("60 минут", f"{claim_minutes} минут")
    return (
        f"📋 <b>Задания</b>\n\n"
        f"{section('Правила', rules)}\n\n"
        f"{blockquote(f'Выберите сервис — бот сразу выдаст задание. Доступно: {platform_count}.')}"
    )


def platforms_list_header(count: int) -> str:
    return tasks_menu_entry_text(count)


def platform_tasks_header(platform_name: str, count: int) -> str:
    return (
        f"📋 <b>{esc_html(platform_name)}</b>\n\n"
        f"{blockquote(f'Шаг 2: выберите заказчика. Доступно: {count}.')}"
    )


def tasks_list_header(count: int) -> str:
    return platforms_list_header(count)


def task_detail_header(task, u: User) -> str:
    name = esc_html(task.customer_name or task.title or f"Задание #{task.id}")
    task_body = name
    if task.link:
        task_body = f"{task_body}\n{esc_html(task.link)}"
    prof = f"Пол: {gender_label(u.gender)}\nTelegram ID: <code>{u.telegram_id}</code>"
    return (
        f"📋 <b>{name}</b>\n\n"
        f"{section('Задание', task_body)}\n\n"
        f"{section_rich('Ваш профиль', prof)}\n\n"
        f"{blockquote('Нажмите «Взять задание» для выбранного текста.')}"
    )


def texts_pick_header(task, texts_total: int, page: int, pages: int) -> str:
    name = esc_html(task.customer_name or task.title or f"Задание #{task.id}")
    link_line = f"\n{esc_html(task.link)}" if task.link else ""
    page_note = f" Страница <b>{page + 1}</b> из <b>{pages}</b>." if pages > 1 else ""
    hint = (
        f"Свободных текстов: {texts_total}. "
        f"Выберите номер кнопкой — текст откроется только после выбора.{page_note}"
    )
    return f"📋 <b>{name}</b>{link_line}\n\n{blockquote_rich(hint)}"


def users_admin_summary_text(
    lines: list[str], *, page: int, pages: int, total: int
) -> str:
    body = "\n\n".join(lines) if lines else "На этой странице никого нет."
    footer = f"Всего пользователей: <b>{total}</b>. Страница <b>{page + 1}</b> из <b>{pages}</b>."
    return f"📊 <b>Сводка пользователей</b>\n\n{body}\n\n{blockquote_rich(footer)}"


def users_admin_list_text(*, page: int, pages: int, total: int) -> str:
    return (
        f"📋 <b>Список пользователей</b>\n\n"
        f"{blockquote(f'Всего: {total}. Страница {page + 1} из {pages}. Выберите пользователя кнопкой.')}"
    )


ASSIGNMENT_WARNING = (
    "Оставьте отзыв строго по тексту задания. "
    "Вознаграждение начисляется после проверки администратором и публикации отзыва."
)


def assignment_message(task, claimed, *, claim_minutes: int = 60, minutes_left: int | None = None) -> str:
    from datetime import datetime

    link = esc_html(task.link or "—")
    text_body = esc_html(claimed.body or "—")
    num = claimed.text_number or claimed.id
    pay = format_reward_rub(task.reward) if task.reward and task.reward > 0 else "не указана"
    left = minutes_left
    if left is None and getattr(claimed, "claimed_at", None):
        elapsed = (datetime.utcnow() - claimed.claimed_at).total_seconds() / 60
        left = max(0, int(claim_minutes - elapsed))
    elif left is None:
        left = claim_minutes
    instr = (task.description or "").strip()
    instr_block = f"{section('Инструкция', instr)}\n\n" if instr else ""
    return (
        f"📥 <b>Задание в работе</b>\n\n"
        f"{section_rich('Срок', f'Осталось около <b>{left}</b> мин из {claim_minutes}.')}\n\n"
        f"{section('Оплата за отзыв', pay)}\n\n"
        f"{instr_block}"
        f"<b>Ссылка</b>\n{link}\n\n"
        f"<b>Текст отзыва №{num}</b>\n{text_body}\n\n"
        f"{blockquote(ASSIGNMENT_WARNING)}"
    )


def admin_submission_review_text(sub, task) -> str:
    u = sub.user
    un = esc_html(f"@{u.username}" if u.username else "—")
    name = esc_html(task.customer_name or task.title or f"Задание #{task.id}")
    done = sub.completed_at or sub.created_at
    done_s = done.strftime("%d.%m.%Y %H:%M") if done else "—"
    executor = (
        f"Username: {un}\n"
        f"Telegram ID: <code>{u.telegram_id}</code>\n"
        f"Имя на площадке: {esc_html(u.platform_account_name or '—')}\n"
        f"Пол: {gender_label(u.gender)}"
    )
    task_info = f"<b>{name}</b>\nСсылка: {task_link_html(task.link)}"
    return (
        f"📝 <b>Отзыв на проверке #{sub.id}</b>\n\n"
        f"{section_rich('Исполнитель', executor)}\n\n"
        f"{section_rich('Задание', task_info)}\n\n"
        f"{section('Текст отзыва', sub.review_text[:3500])}\n\n"
        f"{section('Дата выполнения', done_s)}"
    )


# совместимость
claimed_text_message = assignment_message


def onboarding_welcome(tg: TgUser) -> str:
    return (
        f"👋 <b>Добро пожаловать!</b>\n\n"
        f"{section_rich('Ваш Telegram', tg_peer_lines(tg))}\n\n"
        f"{blockquote('Короткий опрос займёт 1–2 минуты. Шаг 1 из 2 — укажите пол кнопкой ниже.')}"
    )


def admin_home_text(admin_tg: TgUser) -> str:
    return (
        f"🛡 <b>Панель администратора</b>\n\n"
        f"{section_rich('Вы вошли как', tg_peer_lines(admin_tg))}\n\n"
        f"{blockquote('Выберите раздел кнопкой на клавиатуре.')}"
    )


def admin_user_card_text(u: User, done: int, d_act: int, w_act: int, m_act: int) -> str:
    act = "заблокирован" if u.is_banned else "активен"
    stats = (
        f"Выполнено заданий: <b>{done}</b>\n"
        f"Активность (одобр.): день {d_act}, неделя {w_act}, месяц {m_act}\n"
        f"Статус: <b>{act}</b>"
    )
    money = (
        f"Баланс: <b>{u.balance:.2f}</b>\n"
        f"Заработок с заданий: <b>{u.total_earned:.2f}</b>\n"
        f"С рефералов: <b>{u.referral_earned_total:.2f}</b>"
    )
    return (
        f"👤 <b>Карточка пользователя</b>\n\n"
        f"{section_rich('Аккаунт', db_user_lines(u))}\n\n"
        f"{section_rich('Статистика', stats)}\n\n"
        f"{section_rich('Финансы', money)}"
    )


def support_ticket_admin_text(ticket: SupportTicket, user: User) -> str:
    un = esc_html(f"@{user.username}" if user.username else "—")
    who = (
        f"Обращение <b>·#sup{ticket.id}</b>\n"
        f"Пользователь: {un} (ID <code>{user.telegram_id}</code>)\n"
        f"Внутр. ID: <code>{user.id}</code>"
    )
    body = (ticket.text or "—").strip()
    return f"📩 <b>Поддержка</b>\n\n{section_rich('От кого', who)}\n\n{section('Текст', body)}"
