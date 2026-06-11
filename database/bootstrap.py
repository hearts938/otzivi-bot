from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from database.models import AppSetting, Base, Platform, Task, YandexMapsQuestion
from services.yandex_maps import YANDEX_QUIZ_DEFAULT_ORDER_KEY, default_question_order, format_question_order


def _table_names(connection) -> set[str]:
    rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {r[0] for r in rows}


def _sqlite_add_columns(connection) -> None:
    def cols(table: str) -> set[str]:
        rows = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}

    def add(table: str, col: str, ddl: str) -> None:
        if col not in cols(table):
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))

    names = _table_names(connection)
    if "users" in names:
        add("users", "first_name", "VARCHAR(255)")
        add("users", "last_name", "VARCHAR(255)")
        add("users", "total_earned", "FLOAT DEFAULT 0")
        add("users", "referral_earned_total", "FLOAT DEFAULT 0")
        add("users", "is_banned", "BOOLEAN DEFAULT 0")
        add("users", "last_activity_at", "DATETIME")
        add("users", "onboarding_completed", "BOOLEAN DEFAULT 0")
        add("users", "gender", "VARCHAR(16)")
        add("users", "platform_account_name", "VARCHAR(512)")
    if "tasks" in names:
        add("tasks", "platform_id", "INTEGER")
        add("tasks", "customer_name", "VARCHAR(512)")
    if "submissions" in names:
        add("submissions", "cooldown_until", "DATETIME")
        add("submissions", "approved_at", "DATETIME")
        add("submissions", "task_text_id", "INTEGER")
        add("submissions", "completed_at", "DATETIME")
    if "users" in names:
        add("users", "pending_balance", "FLOAT DEFAULT 0")
        add("users", "ban_until", "DATETIME")
        add("users", "work_region", "VARCHAR(255)")
    if "tasks" in names:
        add("tasks", "org_address", "VARCHAR(1024)")
        add("tasks", "region", "VARCHAR(255)")
        add("tasks", "yandex_question_order", "VARCHAR(64)")
    if "yandex_maps_sessions" in names:
        add("yandex_maps_sessions", "quiz_slots", "VARCHAR(64)")
    if "task_texts" in names:
        add("task_texts", "region", "VARCHAR(255)")
        add("task_texts", "text_number", "INTEGER")
        add("task_texts", "required_gender", "VARCHAR(16)")
        add("task_texts", "publish_at", "DATETIME")
        add("task_texts", "published", "BOOLEAN DEFAULT 0")
        add("task_texts", "taken_by_user_id", "INTEGER")
        add("task_texts", "claimed_at", "DATETIME")
    if "withdrawal_requests" in names:
        add("withdrawal_requests", "admin_status", "VARCHAR(32) DEFAULT 'pending'")
        add("withdrawal_requests", "admin_decided_at", "DATETIME")


def _migrate_sync(connection) -> None:
    try:
        dialect = connection.engine.dialect.name
    except Exception:
        dialect = ""
    if dialect == "sqlite":
        _sqlite_add_columns(connection)


async def bootstrap_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sync)


async def seed_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        r = await session.execute(select(Platform).limit(1))
        if r.scalar_one_or_none() is None:
            defaults = [
                ("Яндекс Карты", "yandex_maps", 3600),
                ("2ГИС", "2gis", 3600),
                ("Google Карты", "google_maps", 3600),
                ("Общее", "default", 0),
            ]
            for name, slug, cd in defaults:
                session.add(Platform(name=name, slug=slug, cooldown_seconds=cd, active=True))
            await session.commit()

        r2 = await session.execute(select(Platform).where(Platform.slug == "default"))
        default_pf = r2.scalar_one_or_none()
        if not default_pf:
            session.add(Platform(name="Общее", slug="default", cooldown_seconds=0, active=True))
            await session.commit()
            r2 = await session.execute(select(Platform).where(Platform.slug == "default"))
            default_pf = r2.scalar_one_or_none()

        if default_pf is None:
            await session.commit()
            return

        default_id = default_pf.id
        await session.execute(
            text("UPDATE tasks SET platform_id = :pid WHERE platform_id IS NULL"),
            {"pid": default_id},
        )
        await session.execute(
            text("UPDATE tasks SET customer_name = title WHERE customer_name IS NULL OR customer_name = ''")
        )

        sk = await session.get(AppSetting, "stars_rub_per_star")
        if not sk:
            session.add(AppSetting(key="stars_rub_per_star", value="1.0"))
        cond = await session.get(AppSetting, "yandex_maps_conditions")
        if not cond:
            session.add(
                AppSetting(
                    key="yandex_maps_conditions",
                    value=(
                        "Условия выполнения заданий на Яндекс Картах:\n"
                        "· Соблюдайте инструкции бота\n"
                        "· Отвечайте на контрольные вопросы без спешки\n"
                        "· После паузы 4 ч опубликуйте отзыв по выданному тексту"
                    ),
                )
            )
        question_defaults = [
            (1, 'В разделе «Часы работы» указаны часы открытия в 10:00? Ответьте Да или Нет.'),
            (2, 'На странице организации есть фотографии? Ответьте Да или Нет.'),
            (3, 'Указан номер телефона? Ответьте Да или Нет.'),
            (4, 'Есть кнопка «Построить маршрут»? Ответьте Да или Нет.'),
            (5, 'Указан адрес организации? Ответьте Да или Нет.'),
            (6, 'Есть раздел с отзывами? Ответьте Да или Нет.'),
            (7, 'Указана категория заведения? Ответьте Да или Нет.'),
            (8, 'На карте отображается метка организации? Ответьте Да или Нет.'),
            (9, 'Есть ссылка на сайт? Ответьте Да или Нет.'),
            (10, 'Рейтинг организации отображается? Ответьте Да или Нет.'),
            (11, 'Указаны способы оплаты? Ответьте Да или Нет.'),
            (12, 'Есть описание услуг или меню? Ответьте Да или Нет.'),
            (13, 'Отображается средняя оценка отзывов? Ответьте Да или Нет.'),
            (14, 'Есть кнопка «Позвонить»? Ответьте Да или Нет.'),
            (15, 'Указана станция метро или ориентир рядом? Ответьте Да или Нет.'),
        ]
        r_q = await session.execute(select(YandexMapsQuestion))
        existing_slots = {q.slot for q in r_q.scalars().all()}
        for slot, body in question_defaults:
            if slot not in existing_slots:
                session.add(YandexMapsQuestion(slot=slot, body=body, active=True))
        quiz_order = await session.get(AppSetting, YANDEX_QUIZ_DEFAULT_ORDER_KEY)
        if not quiz_order:
            session.add(
                AppSetting(
                    key=YANDEX_QUIZ_DEFAULT_ORDER_KEY,
                    value=format_question_order(default_question_order()),
                )
            )
        await session.commit()
