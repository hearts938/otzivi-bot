from aiogram.fsm.state import State, StatesGroup


class SupportUserFSM(StatesGroup):
    waiting_text = State()
    waiting_photo = State()


class SupportAdminFSM(StatesGroup):
    waiting_reply = State()
