from html import escape
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from quizbot.domain import Rank, ranked
from quizbot.models import Answer, SessionQuestion, QuizSession, User, Chat, Category


async def ranking(
    tx: AsyncSession,
    session_id: int | None = None,
    chat_id: int | None = None,
    question_id: int | None = None,
) -> list[Rank]:
    query = (
        select(
            User.id,
            User.name,
            func.sum(Answer.points),
            func.sum(case((Answer.option.is_not(None), 1), else_=0)) - func.sum(Answer.points),
            func.sum(case((Answer.correct.is_(True), Answer.elapsed_ms), else_=0)),
        )
        .join(Answer, Answer.user_id == User.id)
        .join(SessionQuestion, SessionQuestion.id == Answer.session_question_id)
        .join(QuizSession, QuizSession.id == SessionQuestion.session_id)
        .join(Chat, Chat.id == QuizSession.chat_id)
        .where(Chat.kind != "channel", Answer.option.is_not(None))
    )
    if session_id is not None:
        query = query.where(QuizSession.id == session_id)
    if chat_id is not None:
        query = query.where(QuizSession.chat_id == chat_id)
    if question_id is not None:
        query = query.where(SessionQuestion.id == question_id)
    rows = (await tx.execute(query.group_by(User.id, User.name))).all()
    return ranked([Rank(int(r[0]), r[1], int(r[2]), int(r[3]), int(r[4])) for r in rows])


def format_ranks(rows: list[Rank], page: int = 0, size: int = 10) -> str:
    if not rows:
        return "Hali aniqlanadigan foydalanuvchi javobi yo‘q."
    lines = []
    for i, r in enumerate(rows[page * size : (page + 1) * size], page * size + 1):
        lines.append(
            f"{i}. {escape(r.name)} — {r.correct} ball | ✅ {r.correct} / ❌ {r.wrong} | "
            f"{r.answered} javob | {r.accuracy:.1f}% | ~{r.elapsed / 1000:.1f} s"
        )
    return "\n".join(lines)


async def personal(tx: AsyncSession, actor: int) -> str:
    rows = (
        await tx.execute(
            select(Category.name, func.count(Answer.id), func.sum(Answer.points))
            .join(QuizSession, QuizSession.category_id == Category.id)
            .join(SessionQuestion, SessionQuestion.session_id == QuizSession.id)
            .join(Answer, Answer.session_question_id == SessionQuestion.id)
            .where(Answer.user_id == actor, Answer.option.is_not(None))
            .group_by(Category.name)
        )
    ).all()
    total = sum(r[1] for r in rows)
    correct = sum(r[2] for r in rows)
    lines = [
        f"📊 Jami: {total} | ✅ {correct} | ❌ {total - correct}",
        f"Aniqlik: {100 * correct / total if total else 0:.1f}%",
        "Kategoriyalar:",
    ]
    lines += [f"• {escape(r[0])}: {r[2]}/{r[1]} ({100 * r[2] / r[1]:.1f}%)" for r in rows]
    recent = (
        await tx.execute(
            select(QuizSession.id, QuizSession.status, Chat.title)
            .join(Chat, Chat.id == QuizSession.chat_id)
            .where(
                QuizSession.id.in_(
                    select(SessionQuestion.session_id)
                    .join(Answer, Answer.session_question_id == SessionQuestion.id)
                    .where(Answer.user_id == actor)
                )
            )
            .order_by(QuizSession.id.desc())
            .limit(5)
        )
    ).all()
    lines.append("Oxirgi sessiyalar:")
    lines += [f"#{r[0]} — {escape(r[2])} ({status_label(r[1])})" for r in recent]
    return "\n".join(lines)


def status_label(status: str) -> str:
    return {
        "active": "faol",
        "paused": "pauzada",
        "stopping": "yakunlanmoqda",
        "finished": "yakunlangan",
        "blocked": "to‘xtatilgan",
    }.get(status, status)
