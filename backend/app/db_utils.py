from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class DatabaseManager:
    def __init__(self, db_config: dict = None):
        self.db_config = db_config
        self._engine = None
        self._session_factory = None
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        db_user = self.db_config.get("db_user", "postgres")
        db_password = self.db_config.get("db_password", "")
        db_host = self.db_config.get("db_host", "localhost")
        db_port = self.db_config.get("db_port", "5432")
        db_name = self.db_config.get("db_name", "paperignition_user")
        database_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        self._engine = create_async_engine(database_url, echo=False, future=True)
        self._session_factory = sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)
        self._initialized = True

    def get_session(self) -> AsyncSession:
        if not self._initialized:
            raise RuntimeError("DatabaseManager not initialized. Call initialize() first.")
        return self._session_factory()

    async def close(self):
        if self._engine:
            await self._engine.dispose()
        self._initialized = False


_db_manager: DatabaseManager = None
_paper_db_manager: DatabaseManager = None


def get_database_manager() -> DatabaseManager:
    return _db_manager

def set_database_manager(db_manager: DatabaseManager):
    global _db_manager
    _db_manager = db_manager

def get_paper_database_manager() -> DatabaseManager:
    return _paper_db_manager

def set_paper_database_manager(db_manager: DatabaseManager):
    global _paper_db_manager
    _paper_db_manager = db_manager


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    db_manager = get_database_manager()
    if not db_manager:
        raise RuntimeError("DatabaseManager not initialized.")
    async with db_manager.get_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_paper_db() -> AsyncGenerator[AsyncSession, None]:
    db_manager = get_paper_database_manager()
    if not db_manager:
        raise RuntimeError("Paper DatabaseManager not initialized.")
    async with db_manager.get_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


from fastapi import HTTPException, Request


def get_index_service_url(request: Request) -> str:
    if not hasattr(request.app.state, 'index_service_url'):
        raise HTTPException(status_code=500, detail="index_service_url not found")
    return request.app.state.index_service_url
