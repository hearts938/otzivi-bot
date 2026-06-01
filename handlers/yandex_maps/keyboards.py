from aiogram.types import ReplyKeyboardMarkup

from handlers.keyboards import (
    BTN_BACK_PLATFORMS,
    BTN_GENDER_F,
    BTN_GENDER_M,
    _kb,
    _rows,
)

BTN_YM_GET = "📥 Получить задания"
BTN_YM_YES = "✅ Да"
BTN_YM_NO = "❌ Нет"
BTN_YM_START = "▶️ Начать"
BTN_YM_REFUSE = "❌ Отказаться"
BTN_YM_Q_YES = "Да"
BTN_YM_Q_NO = "Нет"
BTN_YM_RESET = "🔄 Сбросить задание"


def ym_conditions_kb() -> ReplyKeyboardMarkup:
    return _kb(_rows(BTN_YM_GET, BTN_BACK_PLATFORMS))


def ym_gender_kb():
    return _kb(_rows(BTN_GENDER_M, BTN_GENDER_F, BTN_BACK_PLATFORMS))


def ym_yes_no_kb():
    return _kb(_rows(BTN_YM_YES, BTN_YM_NO))


def ym_quiz_intro_kb():
    return _kb(_rows(BTN_YM_START, BTN_YM_REFUSE))


def ym_question_kb():
    return _kb(_rows(BTN_YM_Q_YES, BTN_YM_Q_NO, BTN_YM_RESET))
