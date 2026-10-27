from aiogram.types import PollAnswer, Poll
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from quizbot.db import Database
from quizbot.models import SessionQuestion, Answer, Chat, QuizSession
from quizbot.repositories.core import now, upsert_user
from quizbot.domain import score


async def accept_answer(
    db: Database, event: PollAnswer, update_id: int, superadmin_id: int
) -> None:
    if event.user is None or event.voter_chat is not None or len(event.option_ids) > 1:
        return
    received = now()
    async with db.sessions.begin() as tx:
        question = await tx.scalar(
            select(SessionQuestion)
            .where(SessionQuestion.poll_id == event.poll_id)
            .with_for_update()
        )
        if not question or question.status not in {"open", "closed"}:
            return
        chat = await tx.get(Chat, question.chat_id)
        if chat.kind == "channel":
            return
        session = await tx.get(QuizSession, question.session_id)
        if chat.kind == "private" and event.user.id != session.owner_id:
            return
        option = event.option_ids[0] if event.option_ids else None
        if option is not None and option not in range(len(question.snapshot["options"])):
            return
        await upsert_user(tx, event.user, superadmin_id)
        points = score(option, question.correct)
        stmt = insert(Answer).values(
            user_id=event.user.id,
            session_question_id=question.id,
            option=option,
            correct=bool(points),
            points=points,
            received_at=received,
            elapsed_ms=max(0, int((received - question.sent_at).total_seconds() * 1000)),
            update_id=update_id,
        )
        await tx.execute(
            stmt.on_conflict_do_update(
                index_elements=[Answer.user_id, Answer.session_question_id],
                set_={
                    k: getattr(stmt.excluded, k)
                    for k in [
                        "option",
                        "correct",
                        "points",
                        "received_at",
                        "elapsed_ms",
                        "update_id",
                    ]
                },
                where=Answer.update_id < update_id,
            )
        )


async def accept_poll(db: Database, poll: Poll, update_id: int) -> None:
    async with db.sessions.begin() as tx:
        q = await tx.scalar(
            select(SessionQuestion).where(SessionQuestion.poll_id == poll.id).with_for_update()
        )
        if q and update_id > q.poll_update_id:
            q.aggregate = {
                "total": poll.total_voter_count,
                "counts": [o.voter_count for o in poll.options],
                "closed": poll.is_closed,
            }
            q.poll_update_id = update_id
            # Closing remains the scheduler's job; it sends the summary and advances once.
