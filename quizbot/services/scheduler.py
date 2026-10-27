import asyncio
import logging
import random
import uuid
from datetime import timedelta
from html import escape
from aiogram import Bot
from aiogram.exceptions import (
    TelegramRetryAfter,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramBadRequest,
    TelegramMigrateToChat,
    TelegramServerError,
)
from aiogram.types import InputPollOption, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from quizbot.db import Database
from quizbot.models import QuizSession, SessionQuestion, Question, Chat
from quizbot.repositories.core import now, question_ids, options
from quizbot.domain import shuffled, validate_question
from quizbot.services.access import bot_can_send
from quizbot.services.results import ranking, format_ranks
from quizbot.services.sessions import block_chat, migrate_chat

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, db: Database, bot: Bot, username: str):
        self.db, self.bot, self.username = db, bot, username
        self.wake = asyncio.Event()
        self.stopped = asyncio.Event()

    async def claim(self) -> tuple[int, str] | None:
        async with self.db.sessions.begin() as tx:
            session = await tx.scalar(
                select(QuizSession)
                .where(
                    QuizSession.status.in_(["active", "paused", "stopping"]),
                    QuizSession.next_run_at <= now(),
                    or_(QuizSession.lease_until.is_(None), QuizSession.lease_until < now()),
                )
                .order_by(QuizSession.next_run_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not session:
                return None
            token = str(uuid.uuid4())
            session.lease_token = token
            session.lease_until = now() + timedelta(seconds=120)
            return session.id, token

    async def run(self) -> None:
        while not self.stopped.is_set():
            try:
                claim = await self.claim()
                if claim:
                    await self.process(*claim)
                    continue
            except Exception as exc:
                logger.error("scheduler_failed", extra={"error_type": type(exc).__name__})
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self.stopped.set()
        self.wake.set()

    async def process(self, session_id: int, token: str) -> None:
        try:
            prepared = await self.prepare(session_id, token)
            if prepared is not None:
                await self.deliver(session_id, token, prepared)
        except TelegramMigrateToChat as exc:
            async with self.db.sessions() as tx:
                session = await tx.get(QuizSession, session_id)
                old = session.chat_id
            await migrate_chat(self.db, old, exc.migrate_to_chat_id)
            await self.failure(session_id, token, "migrate", 1)
        except TelegramRetryAfter as exc:
            await self.failure(session_id, token, "retry_after", exc.retry_after)
        except TelegramForbiddenError:
            async with self.db.sessions() as tx:
                session = await tx.get(QuizSession, session_id)
                chat_id = session.chat_id
            await block_chat(self.db, chat_id, "Telegram botga yuborishni taqiqladi.")
        except (TelegramNetworkError, TelegramServerError, TimeoutError):
            await self.failure(session_id, token, "network")
        except Exception as exc:
            logger.error(
                "job_failed", extra={"session_id": session_id, "error_type": type(exc).__name__}
            )
            await self.failure(session_id, token, "invalid")

    async def prepare(self, session_id: int, token: str) -> int | None:
        async with self.db.sessions.begin() as tx:
            s = await tx.get(QuizSession, session_id, with_for_update=True)
            if s.lease_token != token or s.status not in {"active", "paused", "stopping"}:
                return None
            q = await tx.scalar(
                select(SessionQuestion)
                .where(
                    SessionQuestion.session_id == s.id,
                    SessionQuestion.status.in_(["sending", "open"]),
                )
                .with_for_update()
            )
            if q and q.status == "sending":
                q.status = "uncertain"
                q.closes_at = now() + timedelta(seconds=s.duration + 35)
                s.status = "paused"
                s.reason = "Yuborish natijasi noma’lum. Poll muddati tugagach davom ettiring."
                s.next_run_at = None
                self.release(s)
                return None
            if q:
                if s.status == "active" and q.closes_at > now() and not q.aggregate.get("closed"):
                    s.next_run_at = q.closes_at
                    self.release(s)
                    return None
                try:
                    poll = await self.bot.stop_poll(q.chat_id, q.message_id)
                    q.aggregate = {
                        "total": poll.total_voter_count,
                        "counts": [x.voter_count for x in poll.options],
                        "closed": True,
                    }
                except TelegramBadRequest as exc:
                    if (
                        "already closed" not in exc.message.lower()
                        and "poll has already been closed" not in exc.message.lower()
                    ):
                        raise
                q.status = "closed"
                q.closed_at = now()
                await tx.flush()
                await self.summary(tx, s, q)
                if s.status == "active":
                    if s.total is not None and s.sent >= s.total:
                        await self.finish(tx, s)
                    else:
                        s.next_run_at = now() + timedelta(seconds=s.interval)
                elif s.status == "stopping":
                    await self.finish(tx, s)
                else:
                    s.next_run_at = None
                self.release(s)
                return None
            if s.status == "stopping" or (s.total is not None and s.sent >= s.total):
                await self.finish(tx, s)
                self.release(s)
                return None
            if s.status == "paused":
                s.next_run_at = None
                self.release(s)
                return None
            valid = set(await question_ids(tx, s.category_id))
            queue = [qid for qid in s.queue if qid in valid]
            if not queue and s.total is None:
                queue = list(valid)
                random.SystemRandom().shuffle(queue)
            if not queue:
                await self.finish(tx, s)
                self.release(s)
                return None
            question_id = queue.pop(0)
            question = await tx.get(Question, question_id)
            answers = await options(tx, question_id)
            validate_question(question.text, answers, question.correct, question.explanation)
            answers, correct, order = shuffled(answers, question.correct)
            chat = await tx.get(Chat, s.chat_id)
            if not chat.enabled:
                s.status, s.reason, s.next_run_at = (
                    "blocked",
                    "Chat huquqlari olib tashlangan.",
                    None,
                )
                self.release(s)
                return None
            if chat.kind != "private":
                await bot_can_send(self.bot, chat.id, chat.kind)
            q = SessionQuestion(
                session_id=s.id,
                question_id=question_id,
                chat_id=s.chat_id,
                snapshot={
                    "text": question.text,
                    "options": answers,
                    "order": order,
                    "explanation": question.explanation,
                },
                correct=correct,
                sent_at=now(),
                closes_at=now() + timedelta(seconds=s.duration),
                status="sending",
            )
            tx.add(q)
            s.queue = queue
            await tx.flush()
            return q.id

    async def deliver(self, session_id: int, token: str, question_id: int) -> None:
        async with self.db.sessions.begin() as tx:
            s = await tx.get(QuizSession, session_id, with_for_update=True)
            q = await tx.get(SessionQuestion, question_id, with_for_update=True)
            if s.lease_token != token or q.status != "sending":
                return
            if s.status != "active":
                q.status = "failed"
                s.queue = [q.question_id] + s.queue
                s.next_run_at = now()
                self.release(s)
                return
            chat = await tx.get(Chat, s.chat_id)
            keyboard = None
            if chat.kind == "channel":
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Shaxsiy natija bilan qatnashish",
                                url=f"https://t.me/{self.username}?start=channel_{s.id}",
                            )
                        ]
                    ]
                )
            message = await self.bot.send_poll(
                chat_id=s.chat_id,
                question=q.snapshot["text"],
                options=[InputPollOption(text=t) for t in q.snapshot["options"]],
                type="quiz",
                is_anonymous=chat.kind == "channel",
                allows_multiple_answers=False,
                allows_revoting=False,
                correct_option_ids=[q.correct],
                shuffle_options=False,
                explanation=q.snapshot["explanation"] or None,
                explanation_parse_mode=None,
                question_parse_mode=None,
                open_period=s.duration,
                reply_markup=keyboard,
                request_timeout=30,
            )
            q.poll_id = message.poll.id
            q.message_id = message.message_id
            q.sent_at = message.date
            q.closes_at = message.date + timedelta(seconds=s.duration)
            q.status = "open"
            s.sent += 1
            s.attempts = 0
            s.next_run_at = q.closes_at
            self.release(s)

    async def failure(
        self, session_id: int, token: str, reason: str, delay: int | None = None
    ) -> None:
        async with self.db.sessions.begin() as tx:
            s = await tx.get(QuizSession, session_id, with_for_update=True)
            if s.lease_token != token:
                return
            q = await tx.scalar(
                select(SessionQuestion)
                .where(SessionQuestion.session_id == s.id, SessionQuestion.status == "sending")
                .with_for_update()
            )
            s.attempts += 1
            if q and reason in {"retry_after", "migrate"}:
                q.status = "failed"
                s.queue = [q.question_id] + s.queue
            elif q:
                q.status = "uncertain"
                q.closes_at = now() + timedelta(seconds=s.duration + 35)
                s.status = "paused"
                s.reason = "Yuborilgan-yuborilmagani noma’lum; avtomatik takrorlanmaydi."
                s.next_run_at = None
                self.release(s)
                return
            if reason == "invalid" or s.attempts >= 5:
                s.status, s.next_run_at = "paused", None
                s.reason = "Yuborish xatosi. Huquqlar va sozlamalarni tekshirib davom ettiring."
            else:
                s.next_run_at = now() + timedelta(
                    seconds=delay if delay is not None else min(60, 2**s.attempts)
                )
            self.release(s)

    @staticmethod
    def release(s: QuizSession) -> None:
        s.lease_token = None
        s.lease_until = None

    async def summary(self, tx: AsyncSession, s: QuizSession, q: SessionQuestion) -> None:
        chat = await tx.get(Chat, s.chat_id)
        correct = escape(q.snapshot["options"][q.correct])
        explanation = escape(q.snapshot["explanation"])
        if chat.kind == "channel":
            counts = q.aggregate.get("counts", [])
            total = q.aggregate.get("total", 0)
            good = counts[q.correct] if len(counts) > q.correct else 0
            body = f"📊 Anonim natija: {total} ovoz | ✅ {good} | ❌ {total - good}\nShaxsiy reytingga qo‘shilmaydi."
        else:
            rows = await ranking(tx, question_id=q.id)
            body = (
                f"📊 {sum(r.answered for r in rows)} qatnashchi | ✅ {sum(r.correct for r in rows)} | "
                f"❌ {sum(r.wrong for r in rows)}\n" + format_ranks(rows, size=5)
            )
        await self.bot.send_message(s.chat_id, f"{body}\nTo‘g‘ri javob: {correct}\n{explanation}")

    async def finish(self, tx: AsyncSession, s: QuizSession) -> None:
        s.status, s.next_run_at = "finished", None
        chat = await tx.get(Chat, s.chat_id)
        if chat.kind == "channel":
            questions = (
                await tx.scalars(select(SessionQuestion).where(SessionQuestion.session_id == s.id))
            ).all()
            total = sum(q.aggregate.get("total", 0) for q in questions)
            good = sum(
                q.aggregate.get("counts", [])[q.correct]
                if len(q.aggregate.get("counts", [])) > q.correct
                else 0
                for q in questions
            )
            text = f"🏁 Quiz yakunlandi. {len(questions)} savol, {total} anonim ovoz, {good} to‘g‘ri ovoz.\nBu noyob qatnashchilar soni emas."
            markup = None
        else:
            rows = await ranking(tx, session_id=s.id)
            text = f"🏁 #{s.id} yakuniy reyting\n" + format_ranks(rows)
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="To‘liq reyting", callback_data=f"rank:{s.id}:0")]
                ]
            )
        await self.bot.send_message(s.chat_id, text, reply_markup=markup)
