from aiogram import Router

from handlers.admin import (
    broadcast,
    finance,
    moderation,
    ops,
    panel,
    review,
    support,
    tasks_mgmt,
    users,
    withdrawals,
)

router = Router(name="admin_root")
router.include_router(support.router)
router.include_router(withdrawals.router)
router.include_router(panel.router)
router.include_router(moderation.router)
router.include_router(review.router)
router.include_router(users.router)
router.include_router(broadcast.router)
router.include_router(finance.router)
router.include_router(ops.router)
router.include_router(tasks_mgmt.router)
