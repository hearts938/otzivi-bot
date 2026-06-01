from aiogram.fsm.state import State, StatesGroup


class YandexMapsUserFSM(StatesGroup):
    gender = State()
    yandex_account = State()
    region = State()
    website = State()
