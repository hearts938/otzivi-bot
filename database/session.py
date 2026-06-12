from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.bootstrap import bootstrap_schema, seed_defaults
from database.models import Base


def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def make_engine(database_url: str):
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["timeout"] = 30
    engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine


def make_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(engine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    await bootstrap_schema(engine)
    await seed_defaults(session_factory)


async def get_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
