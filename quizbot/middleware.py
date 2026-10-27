import logging
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import TelegramObject, Message, CallbackQuery
from quizbot.domain import UserError
from quizbot.repositories.core import upsert_user

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except TelegramAPIError:
                pass
        user = getattr(event, "from_user", None)
        if user:
            async with data["db"].sessions.begin() as tx:
                data["db_user"] = await upsert_user(tx, user, data["settings"].superadmin_id)
        try:
            return await handler(event, data)
        except UserError as exc:
            message = event.message if isinstance(event, CallbackQuery) else event
            if isinstance(message, Message):
                await message.answer(str(exc), parse_mode=None)
        except Exception as exc:
            logger.error("handler_failed", extra={"error_type": type(exc).__name__})
            message = event.message if isinstance(event, CallbackQuery) else event
            if isinstance(message, Message):
                try:
                    await message.answer("Amal bajarilmadi. Birozdan so‘ng qayta urinib ko‘ring.")
                except TelegramAPIError:
                    pass
