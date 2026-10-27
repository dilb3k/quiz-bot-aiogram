from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery
from quizbot.db import Database
from quizbot.models import User


class AdminFilter(Filter):
    async def __call__(self, event: Message | CallbackQuery, db: Database) -> bool:
        if not event.from_user:
            return False
        async with db.sessions() as tx:
            user = await tx.get(User, event.from_user.id)
            return bool(user and user.role in {"admin", "superadmin"})
