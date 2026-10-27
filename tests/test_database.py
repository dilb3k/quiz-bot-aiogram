import asyncio
import importlib.util
import os
import uuid
from datetime import timedelta
from pathlib import Path
import pytest
import pytest_asyncio
from aiogram.types import PollAnswer, User as TelegramUser
from sqlalchemy import select, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from quizbot.db import Database
from quizbot.domain import UserError
from quizbot.models import (
    User,
    Chat,
    Category,
    Question,
    QuestionOption,
    QuizSession,
    SessionQuestion,
    Answer,
)
from quizbot.repositories.core import now
from quizbot.services.sessions import create_session, control, migrate_chat
from quizbot.services.scheduler import Scheduler
from quizbot.services.answers import accept_answer
from quizbot.services.results import ranking
from quizbot.services.access import require_role
from quizbot.seed import seed

pytestmark = pytest.mark.database


@pytest_asyncio.fixture
async def db():
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL kerak; production bazaga ulanilmaydi")
    url = make_url(raw)
    if not (url.database or "").endswith("_test") or url.database == "nb_420":
        pytest.fail("Faqat nomi _test bilan tugaydigan alohida test bazasiga ruxsat")
    schema = "quiz_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    obj = object.__new__(Database)
    obj.engine = engine
    obj.sessions = async_sessionmaker(engine, expire_on_commit=False)
    spec = importlib.util.spec_from_file_location(
        "initial", Path(__file__).parents[1] / "migrations/versions/0001_initial.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def migrate(connection):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        yield obj
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def setup(db, kind="private"):
    async with db.sessions.begin() as tx:
        tx.add_all(
            [
                User(id=1, name="Ali", role="user"),
                User(id=2, name="Vali", role="admin"),
                User(id=3, name="Super", role="superadmin"),
            ]
        )
        tx.add(Chat(id=1, title="Sinov", kind=kind, enabled=True))
        c = Category(name="Sinov")
        tx.add(c)
        await tx.flush()
        for i in range(5):
            q = Question(category_id=c.id, text=f"Savol {i}?", correct=0, explanation="Izoh")
            tx.add(q)
            await tx.flush()
            tx.add_all(
                [
                    QuestionOption(question_id=q.id, position=0, text="A"),
                    QuestionOption(question_id=q.id, position=1, text="B"),
                ]
            )
        return c.id


async def create(db):
    cid = await setup(db)
    return await create_session(db, None, 1, 1, cid, 60, 30, 5, 3)


async def sent_question(db, sid):
    async with db.sessions.begin() as tx:
        qid = await tx.scalar(select(Question.id).order_by(Question.id))
        q = SessionQuestion(
            session_id=sid,
            question_id=qid,
            poll_id="poll-1",
            chat_id=1,
            message_id=10,
            snapshot={"text": "Savol?", "options": ["A", "B"], "order": [0, 1], "explanation": ""},
            correct=0,
            status="open",
            sent_at=now() - timedelta(seconds=3),
            closes_at=now() + timedelta(seconds=30),
        )
        tx.add(q)
        await tx.flush()
        return q.id


async def test_admin_roles(db):
    await setup(db)
    async with db.sessions() as tx:
        with pytest.raises(UserError):
            await require_role(tx, 1)
        await require_role(tx, 2)
        with pytest.raises(UserError):
            await require_role(tx, 2, True)
        await require_role(tx, 3, True)


async def test_parallel_sessions_database_constraint(db):
    cid = await setup(db)
    result = await asyncio.gather(
        *[create_session(db, None, 1, 1, cid, 60, 30, 5, 3) for _ in range(8)],
        return_exceptions=True,
    )
    assert sum(isinstance(r, QuizSession) for r in result) == 1
    assert sum(isinstance(r, UserError) for r in result) == 7


async def test_duplicate_changed_and_withdrawn_answers(db):
    s = await create(db)
    await sent_question(db, s.id)
    user = TelegramUser(id=1, is_bot=False, first_name="Ali")
    event = PollAnswer(poll_id="poll-1", user=user, option_ids=[0], option_persistent_ids=["a"])
    await accept_answer(db, event, 100, 3)
    await accept_answer(db, event, 100, 3)
    async with db.sessions() as tx:
        assert await tx.scalar(select(func.count()).select_from(Answer)) == 1
        assert (await ranking(tx, session_id=s.id))[0].correct == 1
    wrong = event.model_copy(update={"option_ids": [1]})
    await accept_answer(db, wrong, 101, 3)
    await accept_answer(db, event, 99, 3)
    async with db.sessions() as tx:
        assert (await ranking(tx, session_id=s.id))[0].wrong == 1
    await accept_answer(db, event.model_copy(update={"option_ids": []}), 102, 3)
    async with db.sessions() as tx:
        assert await ranking(tx, session_id=s.id) == []
        answer = await tx.scalar(select(Answer))
        assert answer.points == 0 and answer.option is None


async def test_channel_never_creates_individual_rank(db):
    s = await create(db)
    await sent_question(db, s.id)
    async with db.sessions.begin() as tx:
        (await tx.get(Chat, 1)).kind = "channel"
    event = PollAnswer(
        poll_id="poll-1",
        user=TelegramUser(id=1, is_bot=False, first_name="Ali"),
        option_ids=[0],
        option_persistent_ids=["a"],
    )
    await accept_answer(db, event, 1, 3)
    async with db.sessions() as tx:
        assert await tx.scalar(select(func.count()).select_from(Answer)) == 0
        assert await ranking(tx, session_id=s.id) == []


async def test_pause_resume_stop_and_owner(db):
    s = await create(db)
    with pytest.raises(UserError):
        await control(db, None, s.id, 2, "pause", 3)
    assert await control(db, None, s.id, 1, "pause", 3) == "paused"
    assert await control(db, None, s.id, 1, "resume", 3) == "active"
    assert await control(db, None, s.id, 1, "stop", 3) == "stopping"
    with pytest.raises(UserError):
        await control(db, None, s.id, 1, "resume", 3)


async def test_worker_claim_exclusive_and_expired_lease(db):
    s = await create(db)
    workers = [Scheduler(db, None, "test_bot") for _ in range(8)]
    claims = await asyncio.gather(*(w.claim() for w in workers))
    assert sum(c is not None for c in claims) == 1
    async with db.sessions.begin() as tx:
        (await tx.get(QuizSession, s.id)).lease_until = now() - timedelta(seconds=1)
    claim = await Scheduler(db, None, "test_bot").claim()
    assert claim[0] == s.id
    assert claim not in claims


async def test_restart_uncertain_delivery_pauses_without_duplicate(db):
    s = await create(db)
    scheduler = Scheduler(db, None, "test_bot")
    sid, token = await scheduler.claim()
    qid = await scheduler.prepare(sid, token)
    async with db.sessions.begin() as tx:
        (await tx.get(QuizSession, s.id)).lease_until = now() - timedelta(seconds=1)
    restarted = Scheduler(db, None, "test_bot")
    claim = await restarted.claim()
    assert await restarted.prepare(*claim) is None
    async with db.sessions() as tx:
        assert (await tx.get(QuizSession, s.id)).status == "paused"
        assert (await tx.get(SessionQuestion, qid)).status == "uncertain"
        assert await tx.scalar(select(func.count()).select_from(SessionQuestion)) == 1
    with pytest.raises(UserError):
        await control(db, None, s.id, 1, "resume", 3)


async def test_seed_idempotent(db):
    await seed(db)
    await seed(db)
    async with db.sessions() as tx:
        assert await tx.scalar(select(func.count()).select_from(Category)) == 3
        assert await tx.scalar(select(func.count()).select_from(Question)) == 15


async def test_snapshot_survives_edit(db):
    s = await create(db)
    qid = await sent_question(db, s.id)
    async with db.sessions.begin() as tx:
        q = await tx.get(SessionQuestion, qid)
        (await tx.get(Question, q.question_id)).text = "Yangi savol"
    async with db.sessions() as tx:
        assert (await tx.get(SessionQuestion, qid)).snapshot["text"] == "Savol?"


async def test_chat_migration_cascades(db):
    s = await create(db)
    qid = await sent_question(db, s.id)
    await migrate_chat(db, 1, -100500)
    async with db.sessions() as tx:
        assert (await tx.get(QuizSession, s.id)).chat_id == -100500
        assert (await tx.get(SessionQuestion, qid)).chat_id == -100500


@pytest_asyncio.fixture
async def simulation_bot():
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    base = os.environ.get("TELEGRAM_SIMULATION_URL")
    if not base:
        pytest.skip(
            "TELEGRAM_SIMULATION_URL yo‘q; HTTP scheduler testi uchun lokal Postman simulyatsiyasi kerak"
        )
    if not base.startswith("http://127.0.0.1:"):
        pytest.fail("Simulyatsiya faqat lokal URL bilan ishlaydi")
    async with Bot(
        "123456:LOCAL_SIMULATION_ONLY",
        session=AiohttpSession(api=TelegramAPIServer.from_base(base), timeout=5),
    ) as bot:
        yield bot


async def run_due(scheduler):
    claim = await scheduler.claim()
    assert claim is not None
    await scheduler.process(*claim)


async def test_restart_closes_expired_poll_and_does_not_spam(db, simulation_bot):
    s = await create(db)
    await run_due(Scheduler(db, simulation_bot, "test_bot"))
    async with db.sessions.begin() as tx:
        q = await tx.scalar(select(SessionQuestion).where(SessionQuestion.session_id == s.id))
        q.closes_at = now() - timedelta(hours=1)
        (await tx.get(QuizSession, s.id)).next_run_at = q.closes_at
    restarted = Scheduler(db, simulation_bot, "test_bot")
    await run_due(restarted)
    async with db.sessions() as tx:
        assert await tx.scalar(select(func.count()).select_from(SessionQuestion)) == 1
        q = await tx.scalar(select(SessionQuestion))
        assert q.status == "closed"
        assert (await tx.get(QuizSession, s.id)).next_run_at > now()
    assert await restarted.claim() is None


async def test_pause_closes_then_resume_sends_next_and_stop_finishes(db, simulation_bot):
    s = await create(db)
    scheduler = Scheduler(db, simulation_bot, "test_bot")
    await run_due(scheduler)
    await control(db, simulation_bot, s.id, 1, "pause", 3)
    with pytest.raises(UserError):
        await control(db, simulation_bot, s.id, 1, "resume", 3)
    await run_due(scheduler)
    async with db.sessions() as tx:
        assert (await tx.scalar(select(SessionQuestion))).status == "closed"
        assert (await tx.get(QuizSession, s.id)).next_run_at is None
    await control(db, simulation_bot, s.id, 1, "resume", 3)
    await run_due(scheduler)
    async with db.sessions() as tx:
        assert await tx.scalar(select(func.count()).select_from(SessionQuestion)) == 2
    await control(db, simulation_bot, s.id, 1, "stop", 3)
    await run_due(scheduler)
    async with db.sessions() as tx:
        assert (await tx.get(QuizSession, s.id)).status == "finished"
        assert (
            await tx.scalar(
                select(func.count())
                .select_from(SessionQuestion)
                .where(SessionQuestion.status == "open")
            )
            == 0
        )


async def test_rate_limit_and_uncertain_retry_policy(db):
    await create(db)
    scheduler = Scheduler(db, None, "test_bot")
    sid, token = await scheduler.claim()
    qid = await scheduler.prepare(sid, token)
    await scheduler.failure(sid, token, "retry_after", 20)
    async with db.sessions.begin() as tx:
        session = await tx.get(QuizSession, sid)
        assert session.next_run_at >= now() + timedelta(seconds=18)
        assert (await tx.get(SessionQuestion, qid)).status == "failed"
        session.next_run_at = now() - timedelta(seconds=1)
    sid, token = await scheduler.claim()
    qid = await scheduler.prepare(sid, token)
    await scheduler.failure(sid, token, "network")
    async with db.sessions() as tx:
        session = await tx.get(QuizSession, sid)
        assert session.status == "paused" and session.next_run_at is None
        assert (await tx.get(SessionQuestion, qid)).status == "uncertain"


async def test_fsm_survives_storage_recreation(db):
    from aiogram.fsm.storage.base import StorageKey
    from quizbot.storage import PostgresStorage

    key = StorageKey(bot_id=123, chat_id=1, user_id=1)
    first = PostgresStorage(db)
    await first.set_state(key, "quiz:duration")
    await first.set_data(key, {"interval": 60})
    second = PostgresStorage(db)
    assert await second.get_state(key) == "quiz:duration"
    assert await second.get_data(key) == {"interval": 60}
