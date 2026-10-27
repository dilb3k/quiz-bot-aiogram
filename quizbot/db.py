from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from quizbot.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.engine.dispose()
