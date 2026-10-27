from aiogram import Router, F, Bot
from aiogram.types import PollAnswer, Poll, ChatMemberUpdated, Message, Update
from quizbot.db import Database
from quizbot.config import Settings
from quizbot.domain import UserError
from quizbot.repositories.core import upsert_chat, upsert_user
from quizbot.services.answers import accept_answer, accept_poll
from quizbot.services.sessions import block_chat, migrate_chat, link_chat
from quizbot.services.access import bot_can_send
from aiogram.exceptions import TelegramAPIError

router = Router(name="events")


@router.poll_answer()
async def poll_answer(
    event: PollAnswer, event_update: Update, db: Database, settings: Settings
) -> None:
    await accept_answer(db, event, event_update.update_id, settings.superadmin_id)


@router.poll()
async def poll(event: Poll, event_update: Update, db: Database) -> None:
    await accept_poll(db, event, event_update.update_id)


@router.my_chat_member()
async def membership(event: ChatMemberUpdated, db: Database, bot: Bot, settings: Settings) -> None:
    chat = event.chat
    async with db.sessions.begin() as tx:
        await upsert_chat(tx, chat.id, chat.title or chat.full_name or str(chat.id), chat.type)
        await upsert_user(tx, event.from_user, settings.superadmin_id)
    try:
        await bot_can_send(bot, chat.id, chat.type)
    except (UserError, TelegramAPIError):
        await block_chat(db, chat.id, "Bot chiqarilgan yoki yuborish huquqlari olib tashlangan.")
        return
    if chat.type != "private":
        try:
            await link_chat(db, bot, event.from_user.id, chat.id)
        except (UserError, TelegramAPIError):
            pass


@router.message(F.migrate_to_chat_id)
async def migrate_to(message: Message, db: Database) -> None:
    await migrate_chat(db, message.chat.id, message.migrate_to_chat_id)


@router.message(F.migrate_from_chat_id)
async def migrate_from(message: Message, db: Database) -> None:
    await migrate_chat(db, message.migrate_from_chat_id, message.chat.id)
