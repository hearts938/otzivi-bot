"""Reply-клавиатуры и подписи кнопок."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# —— Пользователь ——
BTN_TASKS = "📋 Задания"
BTN_PROFILE = "👤 Профиль и баланс"
BTN_WITHDRAW = "💸 Вывести средства"
BTN_REFERRAL = "🔗 Реферальная ссылка"
BTN_SUPPORT = "💬 Поддержка"
BTN_SUPPORT_NO_SCREEN = "Нет"
BTN_BACK_MENU = "◀️ Главное меню"
BTN_BACK_PLATFORMS = "◀️ К сервисам"
BTN_BACK_TASKS = "◀️ К заказчикам"
BTN_TASK_DONE = "✅ Выполнено"
BTN_TASK_REFUSE = "❌ Отказаться от задания"

BTN_GENDER_M = "👨 Мужчина"
BTN_GENDER_F = "👩 Женщина"

BTN_OPEN_ADMIN = "🛡 Админ-панель"
BTN_ADMIN_HOME = BTN_OPEN_ADMIN  # везде одна подпись «Админ-панель»
BTN_USER_MENU = "◀️ Меню пользователя"

USER_MAIN_BUTTONS = frozenset({
    BTN_TASKS,
    BTN_PROFILE,
    BTN_REFERRAL,
    BTN_SUPPORT,
    BTN_SUPPORT_NO_SCREEN,
    BTN_WITHDRAW,
    BTN_BACK_MENU,
    BTN_BACK_PLATFORMS,
    BTN_BACK_TASKS,
    BTN_TASK_DONE,
    BTN_TASK_REFUSE,
})

# —— Админ: главное меню ——
A_USERS_SUM = "📊 Сводка пользователей"
A_USERS_MGMT = "👥 Управление пользователями"
A_USERS_LIST = "📋 Список пользователей"
BTN_BACK_USERS_MENU = "◀️ Пользователи"
A_BROADCAST = "📣 Рассылка"
A_BROADCAST_EXTERNAL = "🔗 Рассылка на другое"
A_REVIEWS_STOCK = "📊 Детализация по отзывам"
A_FINANCE = "💰 Финансы"
A_BALANCE = "💳 Баланс"
BTN_BALANCE_CREDIT = "➕ Начислить"
BTN_BALANCE_DEBIT = "➖ Списать"
A_STARS = "⭐ Курс звёзд"
A_OUTREACH = "✉️ Сообщение пользователю"
A_PF_ADD = "➕ Добавить сервис"
A_PF_DEL = "🗑 Удалить сервис"
A_PF_CD = "⏱ Кулдауны сервисов"
A_TASKS = "📁 Заказчики и тексты"
A_IMPORT_EXCEL = "📥 Импорт из Excel"
A_REVIEW = "📋 Задания на проверке"
A_SUPPORT = "📩 Поддержка"
A_WITHDRAWALS = "💸 Заявки на вывод"
A_YM_QUIZ = "📝 Тест Яндекс Карт"
BTN_YM_QUIZ_EDIT = "✏️ Изменить вопрос"
BTN_YM_QUIZ_LIST = "📋 Пул вопросов"

ADMIN_MAIN_BUTTONS = frozenset({
    BTN_ADMIN_HOME,
    BTN_OPEN_ADMIN,
    A_USERS_SUM,
    A_USERS_MGMT,
    A_USERS_LIST,
    BTN_BACK_USERS_MENU,
    A_BROADCAST,
    A_BROADCAST_EXTERNAL,
    A_REVIEWS_STOCK,
    A_FINANCE,
    A_BALANCE,
    A_STARS,
    A_OUTREACH,
    A_PF_ADD,
    A_PF_DEL,
    A_PF_CD,
    A_TASKS,
    A_IMPORT_EXCEL,
    A_REVIEW,
    A_SUPPORT,
    A_WITHDRAWALS,
    A_YM_QUIZ,
    BTN_YM_QUIZ_EDIT,
    BTN_YM_QUIZ_LIST,
    BTN_BALANCE_CREDIT,
    BTN_BALANCE_DEBIT,
})

# —— Админ: подменю ——
BTN_BACK_REVIEW = "◀️ На проверке"
BTN_BACK_REVIEW_PF = "◀️ Сервисы"

A_TASK_CREATE = "➕ Создать заказчика"
A_TASK_LIST = "📋 Список заказчиков"
BTN_BACK_TASKS_ROOT = "◀️ Заказчики"

A_POOL_ADD = "➕ Текст в пул"
A_POOL_DEL = "🗑 Удалить текст"
A_POOL_IMP = "📥 Excel в пул"
A_POOL_REFRESH = "🔄 Обновить пул"
A_POOL_REWARD = "💰 Изменить оплату"
A_TASK_CHANGE_REWARD = "💰 Изменить оплату заказчика"
A_POOL_DEL_CUST = "❌ Удалить заказчика"
BTN_BACK_TASK_LIST = "◀️ Список заказчиков"

BTN_BACK_FIN = "◀️ Финансы"
BTN_BACK_USER_LIST = "◀️ Список пользователей"

BTN_CANCEL_INPUT = "❌ Отмена"

BTN_PAGE_PREV = "◀️ Предыдущая страница"
BTN_PAGE_NEXT = "▶️ Следующая страница"
BTN_BANK_SEARCH_AGAIN = "🔍 Искать снова"

USERS_PAGE_SIZE = 7
TEXTS_PAGE_SIZE = 8
WITHDRAW_BANKS_PAGE_SIZE = 8


def _kb(rows: list[list[str]], *, persistent: bool = True) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
        is_persistent=persistent,
    )


def _rows(*buttons: str) -> list[list[str]]:
    """По одной кнопке в ряд — на экране выглядят по центру (полная ширина)."""
    return [[b] for b in buttons]


def user_main_kb(*, is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = [
        [BTN_TASKS],
        [BTN_PROFILE],
        [BTN_REFERRAL],
        [BTN_SUPPORT],
    ]
    if is_admin:
        rows.append([BTN_OPEN_ADMIN])
    return _kb(rows)


def user_back_menu_kb() -> ReplyKeyboardMarkup:
    return _kb([[BTN_BACK_MENU]])


def user_profile_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_WITHDRAW, BTN_BACK_MENU))


def withdraw_bank_label(member_id: str, title: str) -> str:
    return f"🏦 {title[:30]} ·#{member_id}"


def parse_withdraw_bank_pick(text: str | None) -> str | None:
    text = _btn_text(text)
    if not text or not text.startswith("🏦") or "·#" not in text:
        return None
    member_id = text.rsplit("·#", 1)[1].strip()
    return member_id or None


def withdraw_banks_kb(bank_labels: list[str], *, page: int, pages: int) -> ReplyKeyboardMarkup:
    rows = [[lbl] for lbl in bank_labels]
    nav: list[str] = []
    if page > 0:
        nav.append(BTN_PAGE_PREV)
    if page < pages - 1:
        nav.append(BTN_PAGE_NEXT)
    if nav:
        rows.append(nav)
    rows.append([BTN_BANK_SEARCH_AGAIN])
    rows.append([BTN_BACK_MENU])
    return _kb(rows)


def user_platforms_kb(labels: list[str]) -> ReplyKeyboardMarkup:
    rows = [[lbl] for lbl in labels[:40]]
    rows.append([BTN_BACK_MENU])
    return _kb(rows)


def user_tasks_kb(labels: list[str]) -> ReplyKeyboardMarkup:
    rows = [[lbl] for lbl in labels[:40]]
    rows.extend(_rows(BTN_BACK_PLATFORMS))
    return _kb(rows)


def user_task_texts_kb(
    labels: list[str], *, show_prev: bool, show_next: bool
) -> ReplyKeyboardMarkup:
    rows = [[lbl] for lbl in labels]
    nav: list[str] = []
    if show_prev:
        nav.append(BTN_PAGE_PREV)
    if show_next:
        nav.append(BTN_PAGE_NEXT)
    if nav:
        rows.append(nav)
    rows.extend(_rows(BTN_BACK_TASKS))
    return _kb(rows)


def admin_users_page_kb(
    pick_labels: list[str] | None,
    *,
    show_prev: bool,
    show_next: bool,
    back_nav: list[str],
) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = [[lbl] for lbl in (pick_labels or [])]
    nav: list[str] = []
    if show_prev:
        nav.append(BTN_PAGE_PREV)
    if show_next:
        nav.append(BTN_PAGE_NEXT)
    if nav:
        rows.append(nav)
    rows.extend([[b] for b in back_nav])
    return _kb(rows)


def user_task_actions_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_TASK_DONE, BTN_TASK_REFUSE, BTN_BACK_PLATFORMS))


def onboarding_gender_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_GENDER_M, BTN_GENDER_F))


def admin_root_kb() -> ReplyKeyboardMarkup:
    return _kb(
        _rows(
            A_USERS_MGMT,
            A_BROADCAST,
            A_BROADCAST_EXTERNAL,
            A_REVIEWS_STOCK,
            A_FINANCE,
            A_BALANCE,
            A_STARS,
            A_OUTREACH,
            A_PF_ADD,
            A_PF_DEL,
            A_PF_CD,
            A_TASKS,
            A_REVIEW,
            A_SUPPORT,
            A_WITHDRAWALS,
            A_YM_QUIZ,
            A_IMPORT_EXCEL,
            BTN_USER_MENU,
            BTN_ADMIN_HOME,
        )
    )


def admin_ym_quiz_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_YM_QUIZ_LIST, BTN_YM_QUIZ_EDIT, BTN_ADMIN_HOME))


def admin_users_menu_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(A_USERS_SUM, A_USERS_LIST, BTN_ADMIN_HOME))


def admin_tasks_root_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(A_TASK_CREATE, A_TASK_LIST, A_TASK_CHANGE_REWARD, BTN_ADMIN_HOME))


def admin_pool_kb() -> ReplyKeyboardMarkup:
    return _kb(
        _rows(
            A_POOL_REWARD,
            A_POOL_ADD,
            A_POOL_DEL,
            A_POOL_IMP,
            A_POOL_REFRESH,
            A_POOL_DEL_CUST,
            BTN_BACK_TASK_LIST,
            BTN_ADMIN_HOME,
        )
    )


def admin_back_home_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_USER_MENU, BTN_ADMIN_HOME))


def admin_labeled_list_kb(labels: list[str], nav_buttons: list[str]) -> ReplyKeyboardMarkup:
    rows = [[lbl] for lbl in labels[:40]]
    rows.extend([[b] for b in nav_buttons])
    return _kb(rows)


def admin_cancel_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_CANCEL_INPUT, BTN_ADMIN_HOME))


def admin_balance_action_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_BALANCE_CREDIT, BTN_BALANCE_DEBIT, BTN_CANCEL_INPUT, BTN_ADMIN_HOME))


def admin_user_card_kb(banned: bool) -> ReplyKeyboardMarkup:
    ban = "✅ Разбанить" if banned else "🚫 Забанить"
    return _kb(_rows(ban, BTN_BACK_USERS_MENU, BTN_ADMIN_HOME))


def admin_moderation_item_kb(sub_id: int) -> ReplyKeyboardMarkup:
    return _kb(
        [
            [f"✅ Одобрить ·#{sub_id}", f"❌ Отклонить ·#{sub_id}"],
            *_rows(BTN_BACK_REVIEW, BTN_ADMIN_HOME),
        ]
    )


def support_photo_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_SUPPORT_NO_SCREEN, BTN_BACK_MENU))


def admin_support_item_kb(ticket_id: int) -> ReplyKeyboardMarkup:
    return _kb(
        [
            [f"✉️ Ответить ·#sup{ticket_id}", f"❌ Отклонить ·#sup{ticket_id}"],
            *_rows(BTN_ADMIN_HOME),
        ]
    )


def admin_withdraw_item_kb(request_id: int) -> ReplyKeyboardMarkup:
    return _kb(
        [
            [f"✅ Подтвердить ·#wd{request_id}", f"❌ Отклонить ·#wd{request_id}"],
            *_rows(BTN_ADMIN_HOME),
        ]
    )


# —— Парсеры подписей кнопок ——

def _btn_text(text: str | None) -> str | None:
    """Безопасно для F.text.func при сообщениях без текста (файл, стикер)."""
    if text is None:
        return None
    s = str(text).strip()
    return s or None


def user_platform_pick_label(platform_id: int, name: str, count: int) -> str:
    short = (name or f"Сервис {platform_id}")[:32]
    return f"🌐 {short} ({count}) ·#upl{platform_id}"


def parse_user_platform_pick(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or "·#upl" not in text or not text.startswith("🌐"):
        return None
    try:
        return int(text.rsplit("·#upl", 1)[1])
    except ValueError:
        return None


def task_pick_label(task_id: int, name: str, reward: float = 0.0) -> str:
    from services.reward_input import format_reward_rub

    short = (name or f"Задание {task_id}")[:30]
    pay = f" · {format_reward_rub(reward)}" if reward and reward > 0 else ""
    return f"📋 {short}{pay} ·#{task_id}"


def parse_task_pick(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or "·#rv" in text or "·#pf" in text or "·#" not in text or not text.startswith("📋"):
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None


def admin_task_pick_label(
    task_id: int, name: str, reward: float = 0.0, region: str | None = None
) -> str:
    from services.reward_input import format_reward_rub

    short = (name or f"Заказчик {task_id}")[:24]
    pay = f" · {format_reward_rub(reward)}" if reward and reward > 0 else ""
    reg = f" · {(region or '')[:12]}" if region else ""
    return f"📁 {short}{reg}{pay} ·#{task_id}"


def parse_admin_task_pick(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or "·#" not in text or not text.startswith("📁"):
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None


def text_pick_label(text_number: int | None, text_id: int) -> str:
    num = text_number or text_id
    return f"📝 Текст №{num} ·#{text_id}"


def take_task_label(text_number: int | None, text_id: int) -> str:
    return text_pick_label(text_number, text_id)


def parse_take_task(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or "·#" not in text:
        return None
    if not (text.startswith("📝") or text.startswith("📥")):
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None


# совместимость
parse_text_pick = parse_take_task


def user_pick_label(username: str | None, telegram_id: int, banned: bool) -> str:
    nick = f"@{username}" if username else "без username"
    st = "🚫" if banned else "✓"
    return f"👤 {st} {nick} · {telegram_id}"


def parse_user_pick_telegram_id(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or not text.startswith("👤"):
        return None
    try:
        return int(text.rsplit("·", 1)[1].strip())
    except (ValueError, IndexError):
        return None


def platform_pick_label(platform_id: int, name: str) -> str:
    return f"🌐 {name[:32]} ·#{platform_id}"


def parse_platform_pick(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or not text.startswith("🌐") or "·#" not in text:
        return None
    if "·#upl" in text or "·#pf" in text or "·#rv" in text:
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None


def finance_platform_label(platform_id: int, name: str) -> str:
    return f"💰 {name[:36]} ·#{platform_id}"


def parse_finance_platform(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or not text.startswith("💰") or "·#" not in text:
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None


def review_platform_label(platform_id: int, name: str, count: int) -> str:
    return f"🔍 {name[:28]} ({count}) ·#pf{platform_id}"


def parse_review_platform(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or "·#pf" not in text or not text.startswith("🔍"):
        return None
    try:
        return int(text.rsplit("·#pf", 1)[1])
    except ValueError:
        return None


def review_task_label(task_id: int, name: str, count: int) -> str:
    short = (name or f"Задание {task_id}")[:30]
    return f"📋 {short} ({count}) ·#rv{task_id}"


def parse_review_task(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or "·#rv" not in text or not text.startswith("📋"):
        return None
    try:
        return int(text.rsplit("·#rv", 1)[1])
    except ValueError:
        return None


def parse_support_action(text: str | None) -> tuple[str, int] | None:
    text = _btn_text(text)
    if not text:
        return None
    if text.startswith("✉️ Ответить ·#sup"):
        try:
            return ("reply", int(text.rsplit("·#sup", 1)[1]))
        except ValueError:
            return None
    if text.startswith("❌ Отклонить ·#sup"):
        try:
            return ("reject", int(text.rsplit("·#sup", 1)[1]))
        except ValueError:
            return None
    return None


def parse_withdraw_action(text: str | None) -> tuple[str, int] | None:
    text = _btn_text(text)
    if not text:
        return None
    if text.startswith("✅ Подтвердить ·#wd"):
        try:
            return ("approve", int(text.rsplit("·#wd", 1)[1]))
        except ValueError:
            return None
    if text.startswith("❌ Отклонить ·#wd"):
        try:
            return ("reject", int(text.rsplit("·#wd", 1)[1]))
        except ValueError:
            return None
    return None


def parse_submission_action(text: str | None) -> tuple[str, int] | None:
    text = _btn_text(text)
    if not text:
        return None
    if text.startswith("✅ Одобрить ·#"):
        try:
            return ("ok", int(text.split("·#", 1)[1]))
        except ValueError:
            return None
    if text.startswith("❌ Отклонить ·#"):
        try:
            return ("no", int(text.split("·#", 1)[1]))
        except ValueError:
            return None
    return None


BAN_TOGGLE_LABELS = frozenset({"🚫 Забанить", "✅ Разбанить"})


def delete_platform_label(platform_id: int, name: str) -> str:
    return f"🗑 {name[:30]} ·#{platform_id}"


def parse_delete_platform(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or not text.startswith("🗑") or "·#" not in text:
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None


def cooldown_platform_label(platform_id: int, name: str, seconds: int) -> str:
    from services.cooldown_input import format_cooldown_hours

    return f"⏱ {name[:24]} ({format_cooldown_hours(seconds)}) ·#{platform_id}"


def parse_cooldown_platform(text: str | None) -> int | None:
    text = _btn_text(text)
    if not text or not text.startswith("⏱") or "·#" not in text:
        return None
    try:
        return int(text.rsplit("·#", 1)[1])
    except ValueError:
        return None
