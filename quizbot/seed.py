import asyncio
from sqlalchemy import select, text
from quizbot.config import Settings
from quizbot.db import Database
from quizbot.models import Category, Question, QuestionOption
from quizbot.demo import DEMO
from quizbot.domain import validate_question


async def seed(db: Database) -> None:
    async with db.sessions.begin() as tx:
        await tx.execute(text("SELECT pg_advisory_xact_lock(4202026)"))
        for name, rows in DEMO.items():
            category = await tx.scalar(select(Category).where(Category.name == name))
            if not category:
                category = Category(name=name)
                tx.add(category)
                await tx.flush()
            for index, (question, options, correct, explanation) in enumerate(rows):
                key = f"demo-v1:{name}:{index}"
                if await tx.scalar(select(Question.id).where(Question.seed_key == key)):
                    continue
                validate_question(question, options, correct, explanation)
                q = Question(
                    category_id=category.id,
                    text=question,
                    correct=correct,
                    explanation=explanation,
                    seed_key=key,
                )
                tx.add(q)
                await tx.flush()
                tx.add_all(
                    [
                        QuestionOption(question_id=q.id, position=i, text=t)
                        for i, t in enumerate(options)
                    ]
                )


async def main() -> None:
    db = Database(Settings())
    try:
        await seed(db)
        print("Demo savollar saqlandi; dublikatlar yaratilmadi.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
