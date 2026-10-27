import asyncio
import json
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand
from sqlalchemy.dialects.postgresql import insert
from quizbot.config import Settings
from quizbot.db import Database
from quizbot.models import User
from quizbot.storage import PostgresStorage, PostgresIsolation
from quizbot.middleware import UserMiddleware
from quizbot.handlers import admin, user, events
from quizbot.services.scheduler import Scheduler


class SafeJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name,
                "event": record.msg if record.name.startswith("quizbot") else "library_event",
                "error_type": getattr(record, "error_type", None),
                "session_id": getattr(record, "session_id", None),
            },
            ensure_ascii=False,
        )


async def main() -> None:
    settings = Settings()
    token = settings.require_token()
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJSONFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    db = Database(settings)
    bot = Bot(
        token, session=AiohttpSession(timeout=35), default=DefaultBotProperties(parse_mode="HTML")
    )
    scheduler = None
    task = None
    dp = Dispatcher(storage=PostgresStorage(db), events_isolation=PostgresIsolation(db))
    dp["db"], dp["settings"] = db, settings
    for observer in [dp.message, dp.callback_query, dp.my_chat_member, dp.poll, dp.poll_answer]:
        observer.outer_middleware(UserMiddleware())
    dp.include_routers(events.router, admin.router, user.router)
    try:
        async with db.sessions.begin() as tx:
            stmt = insert(User).values(
                id=settings.superadmin_id, name="Superadmin", role="superadmin"
            )
            await tx.execute(
                stmt.on_conflict_do_update(index_elements=[User.id], set_={"role": "superadmin"})
            )
        me = await bot.get_me()
        await bot.set_my_commands(
            [
                BotCommand(command=c, description=t)
                for c, t in [
                    ("start", "Asosiy menyu"),
                    ("quiz", "Quiz yaratish"),
                    ("sessions", "Sessiyalar"),
                    ("results", "Natijalarim"),
                    ("ranking", "Reyting"),
                    ("pause", "Pauza"),
                    ("resume", "Davom ettirish"),
                    ("stop", "To‘xtatish"),
                    ("status", "Joriy holat"),
                    ("settings", "Sozlamalar"),
                    ("admin", "Admin panel"),
                    ("cancel", "Bekor qilish"),
                    ("help", "Yordam"),
                ]
            ]
        )
        scheduler = Scheduler(db, bot, me.username)
        dp["scheduler"] = scheduler
        task = asyncio.create_task(scheduler.run())
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_as_tasks=False,
            close_bot_session=False,
        )
    finally:
        if scheduler:
            await scheduler.stop()
        if task:
            await task
        await dp.storage.close()
        await bot.session.close()
        await db.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (ValueError, KeyboardInterrupt) as exc:
        if isinstance(exc, ValueError):
            print("Konfiguratsiya xatosi: BOT_TOKEN va .env sozlamalarini tekshiring.")
    except Exception as exc:
        logging.getLogger(__name__).error(
            "startup_failed", extra={"error_type": type(exc).__name__}
        )
        print("Bot ishga tushmadi. Database, migratsiyalar va tarmoq ulanishini tekshiring.")
        raise SystemExit(1)
