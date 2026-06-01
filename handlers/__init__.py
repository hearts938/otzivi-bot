from handlers.admin import router as admin_router
from handlers.onboarding import router as onboarding_router
from handlers.support_user import router as support_user_router
from handlers.user_handlers import router as user_router
from handlers.yandex_maps import router as yandex_maps_router

__all__ = [
    "onboarding_router",
    "support_user_router",
    "yandex_maps_router",
    "user_router",
    "admin_router",
]
