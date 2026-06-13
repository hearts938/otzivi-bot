from aiogram import Router

from handlers.admin import (
    approved_reviews,
    broadcast,
    broadcast_external,
    finance,
    moderation,
    ops,
    payouts,
    panel,
    review,
    reviews_stock,
    support,
    tasks_mgmt,
    users,
    withdrawals,
    yandex_quiz,
)

router = Router(name="admin_root")
router.include_router(support.router)
router.include_router(withdrawals.router)
router.include_router(payouts.router)
router.include_router(panel.router)
router.include_router(moderation.router)
router.include_router(review.router)
router.include_router(approved_reviews.router)
router.include_router(reviews_stock.router)
router.include_router(users.router)
router.include_router(broadcast.router)
router.include_router(broadcast_external.router)
router.include_router(finance.router)
router.include_router(ops.router)
router.include_router(tasks_mgmt.router)
router.include_router(yandex_quiz.router)
