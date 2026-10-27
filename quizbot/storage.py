from contextlib import asynccontextmanager
import hashlib
from typing import Any, AsyncIterator
from aiogram.fsm.storage.base import BaseStorage, BaseEventIsolation, StorageKey, DefaultKeyBuilder
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from quizbot.models import FSMRecord
from quizbot.db import Database


class PostgresStorage(BaseStorage):
    def __init__(self, db: Database):
        self.db = db
        self.builder = DefaultKeyBuilder(with_bot_id=True, with_destiny=True)

    async def set_state(self, key: StorageKey, state: Any = None) -> None:
        value = state.state if hasattr(state, "state") else state
        async with self.db.sessions.begin() as session:
            stmt = insert(FSMRecord).values(key=self.builder.build(key), state=value, data={})
            await session.execute(
                stmt.on_conflict_do_update(index_elements=[FSMRecord.key], set_={"state": value})
            )

    async def get_state(self, key: StorageKey) -> str | None:
        async with self.db.sessions() as session:
            row = await session.get(FSMRecord, self.builder.build(key))
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        async with self.db.sessions.begin() as session:
            stmt = insert(FSMRecord).values(key=self.builder.build(key), data=data)
            await session.execute(
                stmt.on_conflict_do_update(index_elements=[FSMRecord.key], set_={"data": data})
            )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self.db.sessions() as session:
            row = await session.get(FSMRecord, self.builder.build(key))
            return dict(row.data) if row else {}

    async def close(self) -> None:
        return None


class PostgresIsolation(BaseEventIsolation):
    def __init__(self, db: Database):
        self.db = db

    @asynccontextmanager
    async def lock(self, key: StorageKey) -> AsyncIterator[None]:
        digest = int.from_bytes(
            hashlib.blake2b(str(key).encode(), digest_size=8).digest(), signed=True
        )
        async with self.db.sessions.begin() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": digest})
            yield

    async def close(self) -> None:
        return None
