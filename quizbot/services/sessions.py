import random
from aiogram import Bot
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from quizbot.db import Database
from quizbot.domain import UserError, validate_timing, next_status
from quizbot.models import Chat, QuizSession, SessionQuestion, ChatManager
from quizbot.repositories.core import now, question_ids, upsert_chat
from quizbot.services.access import telegram_admin, bot_can_send, manage


async def link_chat(db: Database, bot: Bot, actor: int, chat_id: int) -> Chat:
    chat = await bot.get_chat(chat_id)
    if chat.type not in {"group", "supergroup", "channel"}:
        raise UserError("Guruh yoki kanalni tanlang.")
    await telegram_admin(bot, chat_id, actor)
    await bot_can_send(bot, chat_id, chat.type)
    async with db.sessions.begin() as tx:
        await upsert_chat(tx, chat.id, chat.title or str(chat.id), chat.type)
        manager = await tx.get(ChatManager, (chat_id, actor))
        if manager:
            manager.checked_at = now()
        else:
            tx.add(ChatManager(chat_id=chat_id, user_id=actor, checked_at=now()))
        return await tx.get(Chat, chat_id)


async def create_session(
    db: Database,
    bot: Bot,
    actor: int,
    chat_id: int,
    category_id: int,
    interval: int,
    duration: int,
    total: int | None,
    superadmin_id: int,
    source: int | None = None,
) -> QuizSession:
    validate_timing(interval, duration)
    if total is not None and total < 1:
        raise UserError("Savollar soni musbat bo‘lsin.")
    try:
        async with db.sessions.begin() as tx:
            chat = await tx.get(Chat, chat_id)
            if not chat:
                raise UserError("Avval chatni ulang.")
            if chat.kind == "private":
                if chat.id != actor:
                    raise UserError("Faqat o‘z shaxsiy chatingizda boshlashingiz mumkin.")
            else:
                if actor != superadmin_id:
                    await telegram_admin(bot, chat_id, actor)
                await bot_can_send(bot, chat_id, chat.kind)
            if not chat.enabled:
                raise UserError("Chatga yuborish to‘xtatilgan. Huquqlarni tiklab, qayta ulang.")
            ids = await question_ids(tx, category_id)
            if not ids:
                raise UserError("Kategoriyada faol savol yo‘q.")
            random.SystemRandom().shuffle(ids)
            if total is not None and total > len(ids):
                raise UserError(f"Hozir {len(ids)} ta savol bor. Sozlamalarni qayta tasdiqlang.")
            session = QuizSession(
                chat_id=chat_id,
                owner_id=actor,
                category_id=category_id,
                interval=interval,
                duration=duration,
                total=total,
                queue=ids,
                created_at=now(),
                next_run_at=now(),
                source_session_id=source,
            )
            tx.add(session)
            await tx.flush()
            return session
    except IntegrityError as exc:
        raise UserError("Bu chatda faol yoki pauzadagi quiz bor. Avval uni to‘xtating.") from exc


async def control(
    db: Database, bot: Bot, session_id: int, actor: int, action: str, superadmin_id: int
) -> str:
    async with db.sessions.begin() as tx:
        session = await tx.scalar(
            select(QuizSession).where(QuizSession.id == session_id).with_for_update()
        )
        if not session:
            raise UserError("Sessiya topilmadi.")
        chat = await manage(bot, tx, session, actor, superadmin_id)
        status = next_status(session.status, action)
        if action == "resume":
            await bot_can_send(bot, chat.id, chat.kind)
            uncertain = await tx.scalar(
                select(SessionQuestion).where(
                    SessionQuestion.session_id == session_id,
                    SessionQuestion.status == "uncertain",
                    SessionQuestion.closes_at > now(),
                )
            )
            closing = await tx.scalar(
                select(SessionQuestion).where(
                    SessionQuestion.session_id == session_id,
                    SessionQuestion.status.in_(["sending", "open"]),
                    SessionQuestion.closes_at > now(),
                )
            )
            if closing:
                raise UserError(
                    "Pauza uchun ochiq savol yopilmoqda. Bir ozdan keyin davom ettiring."
                )
            if uncertain:
                raise UserError(
                    "Oldingi yuborish holati noma’lum. Savol muddati tugagach davom ettiring."
                )
            if not chat.enabled:
                raise UserError("Chatni avval qayta ulang.")
        session.status = status
        session.next_run_at = now()
        session.reason = None
        return status


async def block_chat(db: Database, chat_id: int, reason: str) -> None:
    async with db.sessions.begin() as tx:
        await tx.execute(
            update(Chat).where(Chat.id == chat_id).values(enabled=False, reason=reason)
        )
        await tx.execute(
            update(QuizSession)
            .where(
                QuizSession.chat_id == chat_id,
                QuizSession.status.in_(["active", "paused", "stopping"]),
            )
            .values(status="blocked", reason=reason, next_run_at=None)
        )


async def migrate_chat(db: Database, old_id: int, new_id: int) -> None:
    async with db.sessions.begin() as tx:
        old = await tx.get(Chat, old_id, with_for_update=True)
        if old:
            existing = await tx.get(Chat, new_id)
            if existing:
                await tx.execute(
                    update(QuizSession)
                    .where(
                        QuizSession.chat_id.in_([old_id, new_id]),
                        QuizSession.status.in_(["active", "paused", "stopping"]),
                    )
                    .values(
                        status="blocked",
                        reason="Chat migratsiyasi: qayta sozlab boshlang.",
                        next_run_at=None,
                    )
                )
                await tx.execute(
                    update(QuizSession).where(QuizSession.chat_id == old_id).values(chat_id=new_id)
                )
                await tx.execute(
                    update(SessionQuestion)
                    .where(SessionQuestion.chat_id == old_id)
                    .values(chat_id=new_id)
                )
                managers = (
                    await tx.scalars(select(ChatManager).where(ChatManager.chat_id == old_id))
                ).all()
                for manager in managers:
                    await tx.execute(
                        insert(ChatManager)
                        .values(
                            chat_id=new_id, user_id=manager.user_id, checked_at=manager.checked_at
                        )
                        .on_conflict_do_nothing()
                    )
                await tx.execute(delete(ChatManager).where(ChatManager.chat_id == old_id))
                await tx.delete(old)
                existing.kind = "supergroup"
            else:
                old.id = new_id
                old.kind = "supergroup"
