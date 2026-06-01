from config import Settings


def is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids
