from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import User as TelegramUser
from quizbot.models import User, Chat, Category, Question, QuestionOption


def now() -> datetime:
    return datetime.now(UTC)


async def upsert_user(db: AsyncSession, user: TelegramUser, superadmin_id: int) -> User:
    stmt = insert(User).values(
        id=user.id, name=user.full_name, role="superadmin" if user.id == superadmin_id else "user"
    )
    changes = {"name": user.full_name}
    if user.id == superadmin_id:
        changes["role"] = "superadmin"
    await db.execute(stmt.on_conflict_do_update(index_elements=[User.id], set_=changes))
    return await db.get(User, user.id, populate_existing=True)


async def upsert_chat(
    db: AsyncSession,
    chat_id: int,
    title: str,
    kind: str,
    enabled: bool = True,
    reason: str | None = None,
) -> None:
    stmt = insert(Chat).values(id=chat_id, title=title, kind=kind, enabled=enabled, reason=reason)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Chat.id],
            set_={"title": title, "kind": kind, "enabled": enabled, "reason": reason},
        )
    )


async def categories(db: AsyncSession, active_only: bool = True) -> list[Category]:
    query = select(Category).order_by(Category.name)
    if active_only:
        query = query.where(Category.active.is_(True))
    return list((await db.scalars(query)).all())


async def question_ids(db: AsyncSession, category_id: int) -> list[int]:
    return list(
        (
            await db.scalars(
                select(Question.id)
                .join(Category)
                .where(
                    Question.category_id == category_id,
                    Question.active.is_(True),
                    Category.active.is_(True),
                )
                .order_by(Question.id)
            )
        ).all()
    )


async def options(db: AsyncSession, question_id: int) -> list[str]:
    return list(
        (
            await db.scalars(
                select(QuestionOption.text)
                .where(QuestionOption.question_id == question_id)
                .order_by(QuestionOption.position)
            )
        ).all()
    )
