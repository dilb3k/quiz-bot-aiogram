from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from quizbot.domain import UserError
from quizbot.models import User, QuizSession, Chat


async def require_role(db: AsyncSession, actor: int, super_only: bool = False) -> User:
    user = await db.get(User, actor)
    allowed = {"superadmin"} if super_only else {"admin", "superadmin"}
    if not user or user.role not in allowed:
        raise UserError("Bu amal uchun administrator vakolati kerak.")
    return user


async def telegram_admin(bot: Bot, chat_id: int, actor: int) -> None:
    member = await bot.get_chat_member(chat_id, actor)
    if member.status not in {"creator", "administrator"}:
        raise UserError("Siz bu chatning Telegram administratori emassiz.")


async def bot_can_send(bot: Bot, chat_id: int, kind: str) -> None:
    if kind == "private":
        return
    member = await bot.get_chat_member(chat_id, bot.id)
    if member.status in {"left", "kicked"}:
        raise UserError("Bot chatga qo‘shilmagan.")
    if kind == "channel":
        if member.status != "administrator" or not getattr(member, "can_post_messages", False):
            raise UserError("Botga kanalda administrator va post joylash huquqini bering.")
    elif kind != "private":
        if member.status == "restricted":
            if not getattr(member, "can_send_messages", False) or not getattr(
                member, "can_send_polls", False
            ):
                raise UserError("Botga xabar va so‘rovnoma yuborish huquqini bering.")
        elif member.status not in {"administrator", "creator"}:
            chat = await bot.get_chat(chat_id)
            permissions = chat.permissions
            if permissions and (
                not permissions.can_send_messages or not permissions.can_send_polls
            ):
                raise UserError("Botga xabar va so‘rovnoma yuborish huquqini bering.")


async def manage(
    bot: Bot, db: AsyncSession, session: QuizSession, actor: int, superadmin_id: int
) -> Chat:
    chat = await db.get(Chat, session.chat_id)
    if chat.kind == "private":
        if actor != session.owner_id:
            raise UserError("Bu shaxsiy sessiya sizga tegishli emas.")
    elif actor != superadmin_id:
        await telegram_admin(bot, chat.id, actor)
    return chat
