"""Database session management for Vigil."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from vigil.db.models import Base

log = logging.getLogger(__name__)

# Default to SQLite for simplicity, PostgreSQL for production
DEFAULT_SQLITE_PATH = Path.home() / ".vigil" / "vigil.db"
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_SQLITE_PATH}"
# For PostgreSQL: "postgresql+asyncpg://vigil:vigil@localhost:5432/vigil"


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("VIGIL_DATABASE_URL", DEFAULT_DATABASE_URL)
        self._engine = None
        self._session_factory = None

    async def init(self) -> None:
        """Initialize the database engine and create tables."""
        if self._engine is not None:
            return

        # Ensure directory exists for SQLite
        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.replace("sqlite+aiosqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            log.info("Using SQLite database: %s", db_path)
            self._engine = create_async_engine(
                self.database_url,
                echo=False,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            log.info("Connecting to database: %s", self.database_url.split("@")[-1])
            self._engine = create_async_engine(
                self.database_url,
                echo=False,
                poolclass=NullPool,
            )

        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        log.info("Database initialized successfully")

    async def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        if self._session_factory is None:
            await self.init()

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


_db_manager: Optional[DatabaseManager] = None


async def init_db(database_url: Optional[str] = None) -> DatabaseManager:
    """Initialize the global database manager."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(database_url)
        await _db_manager.init()
    return _db_manager


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting a database session."""
    if _db_manager is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _db_manager.session() as session:
        yield session


def get_db_manager() -> Optional[DatabaseManager]:
    """Get the global database manager."""
    return _db_manager
