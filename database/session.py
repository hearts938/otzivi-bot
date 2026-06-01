from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.bootstrap import bootstrap_schema, seed_defaults
from database.models import Base


def make_engine(database_url: str):
    return create_async_engine(database_url, echo=False)


def make_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(engine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    await bootstrap_schema(engine)
    await seed_defaults(session_factory)


async def get_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
