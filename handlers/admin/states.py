from aiogram.fsm.state import State, StatesGroup


class AdminImport(StatesGroup):
    waiting_file = State()


class BroadcastFSM(StatesGroup):
    text = State()
    button = State()
    photo = State()


class BalanceFSM(StatesGroup):
    user_ref = State()
    action = State()
    amount = State()


class StarsFSM(StatesGroup):
    rate = State()


class OutreachFSM(StatesGroup):
    user_ref = State()
    message = State()


class PlatformAddFSM(StatesGroup):
    name = State()
    slug = State()
    cooldown = State()


class PlatformCdFSM(StatesGroup):
    seconds = State()


class CustomerAddFSM(StatesGroup):
    platform_pick = State()
    name = State()
    link = State()
    reward = State()
    customer_region = State()
    instruction = State()
    org_address = State()
    question_order = State()


class TaskRewardFSM(StatesGroup):
    amount = State()


class ManualTextFSM(StatesGroup):
    gender = State()
    body = State()
    publish_date = State()


class DeleteTextsFSM(StatesGroup):
    numbers = State()


class AdminUsersBrowse(StatesGroup):
    summary = State()
    list_pick = State()
