from html import escape
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func, delete
from quizbot.db import Database
from quizbot.config import Settings
from quizbot.models import Category, Question, QuestionOption, User, Chat, QuizSession, Answer
from quizbot.filters import AdminFilter
from quizbot.services.access import require_role
from quizbot.repositories.core import categories, options
from quizbot.domain import UserError, validate_question
from quizbot.keyboards.common import inline

router = Router(name="admin")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


def nav() -> list[list[tuple[str, str]]]:
    return [[("⬅️ Orqaga", "adm:back"), ("Bekor qilish", "adm:cancel")]]


@router.message(F.text == "🛠 Admin panel")
@router.message(Command("admin"))
async def panel(message: Message, state: FSMContext, db: Database) -> None:
    if message.chat.type != "private":
        raise UserError("Admin panelni botning shaxsiy chatida oching.")
    await state.clear()
    async with db.sessions() as tx:
        user = await require_role(tx, message.from_user.id)
    rows = [
        [("Kategoriyalar", "adm:categories"), ("Kategoriya yaratish", "adm:newcategory")],
        [("Savollar", "adm:questions"), ("Savol qo‘shish", "adm:newquestion")],
        [("Bot statistikasi", "adm:stats")],
    ]
    if user.role == "superadmin":
        rows += [
            [("Admin tayinlash", "adm:grant"), ("Adminni olib tashlash", "adm:revoke")],
            [("Adminlar ro‘yxati", "adm:admins")],
        ]
    await message.answer("🛠 Admin panel", reply_markup=inline(rows))


@router.callback_query(F.data.startswith("adm:"))
async def actions(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if call.message.chat.type != "private":
        raise UserError("Admin panel shaxsiy chatda ishlaydi.")
    action = call.data.split(":")[1]
    async with db.sessions() as tx:
        await require_role(tx, call.from_user.id, action in {"grant", "revoke", "admins"})
    if action == "cancel":
        await state.clear()
        await call.message.answer("Bekor qilindi.")
    elif action == "back":
        current = await state.get_state()
        back = {
            "admin:qtext": "admin:qcategory",
            "admin:qoptions": "admin:qtext",
            "admin:qcorrect": "admin:qoptions",
            "admin:qexplanation": "admin:qcorrect",
            "admin:qpreview": "admin:qexplanation",
        }
        if current in back:
            await state.set_state(back[current])
            await prompt(call.message, state, db)
        else:
            await state.clear()
            await call.message.answer("Admin panelga qaytish: /admin")
    elif action in {"newcategory", "grant", "revoke"}:
        await state.clear()
        await state.set_state("admin:" + action)
        await call.message.answer(
            "Kategoriya nomini kiriting (1–100 belgi):"
            if action == "newcategory"
            else "Telegram user IDni kiriting:",
            reply_markup=inline(nav()),
        )
    elif action == "categories":
        async with db.sessions() as tx:
            rows = await categories(tx, False)
        await call.message.answer(
            "Kategoriyalar:",
            reply_markup=inline(
                [[(f"{'✅' if c.active else '⏸'} {c.name}", f"cat:{c.id}")] for c in rows]
            ),
        )
    elif action in {"newquestion", "questions"}:
        await state.clear()
        await state.set_state("admin:qcategory" if action == "newquestion" else "admin:browse")
        await prompt(call.message, state, db)
    elif action == "stats":
        async with db.sessions() as tx:
            values = [
                await tx.scalar(select(func.count()).select_from(model))
                for model in [User, Chat, Category, Question, QuizSession, Answer]
            ]
        await call.message.answer(
            "\n".join(
                f"{name}: {value}"
                for name, value in zip(
                    [
                        "Foydalanuvchilar",
                        "Chatlar",
                        "Kategoriyalar",
                        "Savollar",
                        "Sessiyalar",
                        "Javob yozuvlari",
                    ],
                    values,
                )
            )
        )
    elif action == "admins":
        async with db.sessions() as tx:
            admins = (
                await tx.scalars(
                    select(User).where(User.role.in_(["admin", "superadmin"])).order_by(User.id)
                )
            ).all()
        lines = [f"{u.id} — {escape(u.name)} ({u.role})" for u in admins]
        for offset in range(0, max(1, len(lines)), 20):
            await call.message.answer("\n".join(lines[offset : offset + 20]) or "Adminlar yo‘q.")


@router.callback_query(F.data.startswith("cat:"))
async def category_view(call: CallbackQuery, db: Database) -> None:
    async with db.sessions() as tx:
        await require_role(tx, call.from_user.id)
        c = await tx.get(Category, int(call.data.split(":")[1]))
        if not c:
            raise UserError("Kategoriya topilmadi.")
    await call.message.answer(
        escape(c.name),
        reply_markup=inline(
            [
                [("Nomini tahrirlash", f"catrename:{c.id}")],
                [("Deaktiv / aktiv", f"cattoggle:{c.id}:{int(not c.active)}")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("catrename:"))
async def category_rename(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state("admin:rename")
    await state.set_data({"category_id": int(call.data.split(":")[1])})
    await call.message.answer("Yangi nom:", reply_markup=inline(nav()))


@router.callback_query(F.data.startswith("cattoggle:"))
async def category_toggle(call: CallbackQuery, db: Database) -> None:
    async with db.sessions.begin() as tx:
        await require_role(tx, call.from_user.id)
        c = await tx.get(Category, int(call.data.split(":")[1]), with_for_update=True)
        if not c:
            raise UserError("Kategoriya topilmadi.")
        c.active = call.data.split(":")[2] == "1"
    await call.message.answer("Kategoriya holati yangilandi.")


async def prompt(message: Message, state: FSMContext, db: Database) -> None:
    step = await state.get_state()
    data = await state.get_data()
    rows = []
    if step in {"admin:qcategory", "admin:browse"}:
        text = "Kategoriyani tanlang:"
        async with db.sessions() as tx:
            rows = [[(c.name, f"acat:{c.id}")] for c in await categories(tx, False)]
    elif step == "admin:qtext":
        text = "Savol matni (1–300 belgi):"
    elif step == "admin:qoptions":
        text = "2–4 variantni alohida qatorlarda kiriting (har biri 1–100 belgi):"
    elif step == "admin:qcorrect":
        text = f"To‘g‘ri variant raqami (1–{len(data['options'])}):"
    elif step == "admin:qexplanation":
        text = "Tushuntirish (200 belgigacha, ko‘pi bilan 2 yangi qator). Kerak bo‘lmasa: -"
    elif step == "admin:qpreview":
        text = (
            escape(data["text"])
            + "\n"
            + "\n".join(
                f"{'✅' if i == data['correct'] else '▫️'} {i + 1}. {escape(v)}"
                for i, v in enumerate(data["options"])
            )
            + "\n"
            + escape(data["explanation"])
        )
        rows = [[("Saqlash", "asave")]]
    else:
        text = "Menyu: /admin"
    await message.answer(text, reply_markup=inline(rows + nav()))


@router.callback_query(F.data.startswith("acat:"))
async def choose_category(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    current = await state.get_state()
    if current not in {"admin:qcategory", "admin:browse"}:
        raise UserError("Tugma eskirgan.")
    cid = int(call.data.split(":")[1])
    async with db.sessions() as tx:
        if not await tx.get(Category, cid):
            raise UserError("Kategoriya topilmadi.")
    await state.update_data(category_id=cid)
    if current == "admin:browse":
        await state.clear()
        await question_list(call.message, db, cid, 0)
    else:
        await state.set_state("admin:qtext")
        await prompt(call.message, state, db)


async def question_list(message: Message, db: Database, cid: int, page: int) -> None:
    async with db.sessions() as tx:
        qs = (
            await tx.scalars(
                select(Question)
                .where(Question.category_id == cid)
                .order_by(Question.id)
                .offset(page * 10)
                .limit(11)
            )
        ).all()
    rows = [[(f"{'✅' if q.active else '⏸'} #{q.id} {q.text[:40]}", f"aq:{q.id}")] for q in qs[:10]]
    if page:
        rows.append([("⬅️", f"aql:{cid}:{page - 1}")])
    if len(qs) > 10:
        rows.append([("➡️", f"aql:{cid}:{page + 1}")])
    await message.answer("Savollar:" if qs else "Savollar yo‘q.", reply_markup=inline(rows))


@router.callback_query(F.data.startswith("aql:"))
async def question_page(call: CallbackQuery, db: Database) -> None:
    _, cid, page = call.data.split(":")
    await question_list(call.message, db, int(cid), max(0, int(page)))


@router.callback_query(F.data.startswith("aq:"))
async def question_view(call: CallbackQuery, db: Database) -> None:
    async with db.sessions() as tx:
        q = await tx.get(Question, int(call.data.split(":")[1]))
        if not q:
            raise UserError("Savol topilmadi.")
        opts = await options(tx, q.id)
    await call.message.answer(
        escape(q.text)
        + "\n"
        + "\n".join(
            f"{i + 1}. {escape(v)} {'✅' if i == q.correct else ''}" for i, v in enumerate(opts)
        )
        + "\n"
        + escape(q.explanation),
        reply_markup=inline(
            [
                [
                    ("Tahrirlash", f"aqedit:{q.id}"),
                    ("Deaktiv / aktiv", f"aqtoggle:{q.id}:{int(not q.active)}"),
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("aqtoggle:"))
async def question_toggle(call: CallbackQuery, db: Database) -> None:
    async with db.sessions.begin() as tx:
        await require_role(tx, call.from_user.id)
        q = await tx.get(Question, int(call.data.split(":")[1]), with_for_update=True)
        if not q:
            raise UserError("Savol topilmadi.")
        q.active = call.data.split(":")[2] == "1"
    await call.message.answer("Savol holati yangilandi.")


@router.callback_query(F.data.startswith("aqedit:"))
async def question_edit(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.sessions() as tx:
        q = await tx.get(Question, int(call.data.split(":")[1]))
        if not q:
            raise UserError("Savol topilmadi.")
    await state.set_data({"question_id": q.id, "category_id": q.category_id})
    await state.set_state("admin:qcategory")
    await prompt(call.message, state, db)


@router.message(
    StateFilter(
        "admin:newcategory",
        "admin:rename",
        "admin:grant",
        "admin:revoke",
        "admin:qtext",
        "admin:qoptions",
        "admin:qcorrect",
        "admin:qexplanation",
    ),
    F.text,
)
async def admin_text(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    current = await state.get_state()
    value = message.text.strip()
    data = await state.get_data()
    if value == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.")
        return
    async with db.sessions.begin() as tx:
        await require_role(tx, message.from_user.id, current in {"admin:grant", "admin:revoke"})
        if current in {"admin:newcategory", "admin:rename"}:
            if not 1 <= len(value) <= 100:
                raise UserError("Nom 1–100 belgi bo‘lsin.")
            exists = await tx.scalar(select(Category).where(Category.name == value))
            if exists:
                raise UserError("Bunday nomli kategoriya mavjud.")
            if current == "admin:newcategory":
                tx.add(Category(name=value))
            else:
                c = await tx.get(Category, data["category_id"])
                if not c:
                    raise UserError("Kategoriya topilmadi.")
                c.name = value
        elif current in {"admin:grant", "admin:revoke"}:
            if not value.isdigit() or not 0 < int(value) < 2**63:
                raise UserError("To‘g‘ri Telegram user ID kiriting.")
            uid = int(value)
            user = await tx.get(User, uid, with_for_update=True)
            if uid == settings.superadmin_id or (user and user.role == "superadmin"):
                raise UserError("Superadmin roli o‘zgartirilmaydi.")
            if not user:
                user = User(id=uid, name=str(uid), role="user")
                tx.add(user)
            user.role = "admin" if current == "admin:grant" else "user"
    if current in {"admin:newcategory", "admin:rename", "admin:grant", "admin:revoke"}:
        await state.clear()
        await message.answer("Saqlandi. /admin")
        return
    if current == "admin:qtext":
        if not 1 <= len(value) <= 300:
            raise UserError("Savol 1–300 belgi bo‘lsin.")
        await state.update_data(text=value)
        next_step = "qoptions"
    elif current == "admin:qoptions":
        opts = [x.strip() for x in value.splitlines()]
        validate_question(data["text"], opts, 0)
        await state.update_data(options=opts)
        next_step = "qcorrect"
    elif current == "admin:qcorrect":
        if not value.isdigit() or int(value) not in range(1, len(data["options"]) + 1):
            raise UserError("Variant raqami noto‘g‘ri.")
        await state.update_data(correct=int(value) - 1)
        next_step = "qexplanation"
    else:
        explanation = "" if value == "-" else value
        validate_question(data["text"], data["options"], data["correct"], explanation)
        await state.update_data(explanation=explanation)
        next_step = "qpreview"
    await state.set_state("admin:" + next_step)
    await prompt(message, state, db)


@router.callback_query(F.data == "asave")
async def save_question(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if await state.get_state() != "admin:qpreview":
        raise UserError("Bu preview eskirgan.")
    data = await state.get_data()
    validate_question(data["text"], data["options"], data["correct"], data["explanation"])
    async with db.sessions.begin() as tx:
        await require_role(tx, call.from_user.id)
        if not await tx.get(Category, data["category_id"]):
            raise UserError("Kategoriya topilmadi.")
        q = (
            await tx.get(Question, data["question_id"], with_for_update=True)
            if data.get("question_id")
            else Question()
        )
        if not q:
            raise UserError("Savol topilmadi.")
        q.category_id, q.text, q.correct, q.explanation = (
            data["category_id"],
            data["text"],
            data["correct"],
            data["explanation"],
        )
        tx.add(q)
        await tx.flush()
        await tx.execute(delete(QuestionOption).where(QuestionOption.question_id == q.id))
        tx.add_all(
            [
                QuestionOption(question_id=q.id, position=i, text=t)
                for i, t in enumerate(data["options"])
            ]
        )
    await state.clear()
    await call.message.answer("✅ Savol saqlandi. Eski sessiyalar nusxasi o‘zgarmadi.")
