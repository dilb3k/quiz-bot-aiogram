from html import escape
from zoneinfo import ZoneInfo
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from quizbot.services.scheduler import Scheduler
from quizbot.models import Chat, ChatManager, QuizSession, SessionQuestion, Answer, User
from quizbot.db import Database
from quizbot.config import Settings
from quizbot.repositories.core import upsert_chat, categories, question_ids
from quizbot.domain import UserError, validate_timing
from quizbot.services.sessions import create_session, control, link_chat
from quizbot.services.access import manage
from quizbot.services.results import ranking, format_ranks, personal, status_label
from quizbot.keyboards.common import menu, inline, navigation, controls, chat_picker

router = Router(name="user")


async def private_only(message: Message) -> None:
    if message.chat.type != "private":
        raise UserError(
            "Quiz sozlash uchun botning shaxsiy chatiga o‘ting. Bu chatda /status, /pause, /resume, /stop va /ranking ishlaydi."
        )


@router.message(CommandStart())
async def start(message: Message, db: Database, db_user: User, state: FSMContext) -> None:
    await state.clear()
    if message.chat.type == "private":
        async with db.sessions.begin() as tx:
            await upsert_chat(tx, message.chat.id, message.from_user.full_name, "private")
    await message.answer(
        "Assalomu alaykum! Quiz menyusi:", reply_markup=menu(db_user.role != "user")
    )
    payload = (message.text or "").split(maxsplit=1)
    if len(payload) == 2 and payload[1].startswith("channel_"):
        await private_only(message)
        try:
            source_id = int(payload[1].split("_", 1)[1])
        except ValueError:
            raise UserError("Havola noto‘g‘ri.")
        async with db.sessions() as tx:
            source = await tx.get(QuizSession, source_id)
            chat = await tx.get(Chat, source.chat_id) if source else None
            if not source or chat.kind != "channel":
                raise UserError("Kanal sessiyasi topilmadi.")
        await state.set_state("quiz:category")
        await state.set_data(
            {"chat_id": message.from_user.id, "kind": "private", "source": source_id}
        )
        await show_step(message, state, db)
        await message.answer(
            "Bu alohida shaxsiy quiz. Natijalar kanalning anonim ovozlariga qo‘shilmaydi."
        )


@router.message(F.text == "🧠 Quiz boshlash")
@router.message(Command("quiz"))
async def begin(message: Message, state: FSMContext, db: Database) -> None:
    await private_only(message)
    async with db.sessions.begin() as tx:
        await upsert_chat(tx, message.from_user.id, message.from_user.full_name, "private")
    await state.clear()
    await state.set_state("quiz:place")
    await show_step(message, state, db)


async def show_step(message: Message, state: FSMContext, db: Database) -> None:
    step = (await state.get_state() or "").split(":")[-1]
    data = await state.get_data()
    rows: list[list[tuple[str, str]]] = []
    text = ""
    if step == "place":
        text = "Quiz qayerda o‘tkazilsin?"
        rows = [
            [("O‘zim uchun", "q:place:private")],
            [("Guruh uchun", "q:place:group")],
            [("Kanal uchun", "q:place:channel")],
        ]
    elif step == "chat":
        text = "Ulangan chatni tanlang. Ro‘yxatda yo‘q bo‘lsa, avval menyudagi ulash tugmasidan foydalaning."
        async with db.sessions() as tx:
            chats = (
                await tx.scalars(
                    select(Chat)
                    .join(ChatManager)
                    .where(
                        ChatManager.user_id == data["actor"],
                        Chat.kind.in_(
                            ["group", "supergroup"] if data["kind"] == "group" else ["channel"]
                        ),
                    )
                    .order_by(Chat.title)
                )
            ).all()
        rows = [[(c.title[:50], f"q:chat:{c.id}")] for c in chats]
    elif step == "category":
        text = "Aktiv kategoriyani tanlang:"
        async with db.sessions() as tx:
            rows = [[(c.name, f"q:category:{c.id}")] for c in await categories(tx)]
    elif step == "interval":
        text = "Savol yopilgandan keyingi interval:"
        rows = [
            [(label, f"q:interval:{value}")]
            for label, value in [
                ("1 daqiqa", 60),
                ("5 daqiqa", 300),
                ("15 daqiqa", 900),
                ("30 daqiqa", 1800),
                ("1 soat", 3600),
                ("Boshqa interval", 0),
            ]
        ]
    elif step == "custom":
        text = "Intervalni butun minutda kiriting (1–1440):"
    elif step == "duration":
        text = "Har savolga javob muddati (soniya):"
        rows = [
            [(f"{n} soniya", f"q:duration:{n}") for n in [15, 30, 60]],
            [("5 daqiqa", "q:duration:300"), ("Boshqa muddat", "q:duration:0")],
        ]
    elif step == "duration_custom":
        text = "Javob muddatini butun soniyada kiriting (5–2628000):"
    elif step == "count":
        text = "Savollar soni:"
        rows = [
            [(str(n), f"q:count:{n}") for n in [5, 10, 20]],
            [("Kategoriyadagi hammasi", "q:count:all")],
            [("Davomiy rejim", "q:count:continuous")],
        ]
    elif step == "confirm":
        text = (
            f"Chat: {data['chat_id']}\nKategoriya: {escape(data['category_name'])}\n"
            f"Interval: {data['interval'] // 60} daqiqa\nJavob muddati: {data['duration']} soniya\n"
            f"Savollar: {data['total'] if data['total'] else 'davomiy rejim'}\n"
        )
        if data.get("shortage"):
            text += f"So‘ralganidan kam: faqat {data['total']} ta faol savol bor. Mavjud savollar bilan boshlaysizmi?\n"
        rows = [[("✅ Boshlash", "q:confirm:yes")]]
    await message.answer(
        text or "Menyudan qayta boshlang.", reply_markup=inline(rows + navigation())
    )


@router.callback_query(F.data.startswith("q:"))
async def quiz_choice(
    call: CallbackQuery,
    state: FSMContext,
    db: Database,
    bot: Bot,
    settings: Settings,
    scheduler: Scheduler,
) -> None:
    await private_only(call.message)
    _, step, value = call.data.split(":", 2)
    if await state.get_state() != f"quiz:{step}":
        raise UserError("Bu tugma eskirgan. Joriy bosqichdan davom eting.")
    data = await state.get_data()
    if step == "place":
        if value not in {"private", "group", "channel"}:
            raise UserError("Joy noto‘g‘ri.")
        await state.update_data(kind=value, actor=call.from_user.id)
        if value == "private":
            await state.update_data(chat_id=call.from_user.id)
        next_step = "category" if value == "private" else "chat"
    elif step == "chat":
        chat = await link_chat(db, bot, call.from_user.id, int(value))
        if (chat.kind == "channel") != (data["kind"] == "channel"):
            raise UserError("Chat turi tanlovga mos emas.")
        await state.update_data(chat_id=chat.id)
        next_step = "category"
    elif step == "category":
        async with db.sessions() as tx:
            available = {c.id: c.name for c in await categories(tx)}
        if int(value) not in available:
            raise UserError("Kategoriya faol emas.")
        await state.update_data(category_id=int(value), category_name=available[int(value)])
        next_step = "interval"
    elif step == "interval":
        interval = int(value)
        if interval:
            validate_timing(interval, 30)
            await state.update_data(interval=interval)
        next_step = "duration" if interval else "custom"
    elif step == "duration":
        duration = int(value)
        if duration:
            validate_timing(data["interval"], duration)
            await state.update_data(duration=duration)
        next_step = "count" if duration else "duration_custom"
    elif step == "count":
        async with db.sessions() as tx:
            count = len(await question_ids(tx, data["category_id"]))
        if not count:
            raise UserError("Faol savol yo‘q. Boshqa kategoriya tanlang.")
        requested = None if value == "continuous" else count if value == "all" else int(value)
        if requested is not None and requested < 1:
            raise UserError("Savollar soni noto‘g‘ri.")
        await state.update_data(
            total=min(count, requested) if requested else None,
            shortage=bool(requested and requested > count),
        )
        next_step = "confirm"
    elif step == "confirm":
        session = await create_session(
            db,
            bot,
            call.from_user.id,
            data["chat_id"],
            data["category_id"],
            data["interval"],
            data["duration"],
            data["total"],
            settings.superadmin_id,
            data.get("source"),
        )
        await state.clear()
        scheduler.wake.set()
        await call.message.answer(
            f"Quiz #{session.id} boshlandi. Birinchi savol yuborilmoqda.",
            reply_markup=controls(session.id),
        )
        return
    else:
        raise UserError("Tanlov noto‘g‘ri.")
    await state.set_state(f"quiz:{next_step}")
    await show_step(call.message, state, db)


@router.message(F.text, F.text.regexp(r"^\d+$"))
async def numeric_input(message: Message, state: FSMContext, db: Database) -> None:
    current = await state.get_state()
    if current not in {"quiz:custom", "quiz:duration_custom"}:
        raise UserError("Menyudagi amalni tanlang.")
    value = int(message.text)
    if current == "quiz:custom":
        validate_timing(value * 60, 30)
        await state.update_data(interval=value * 60)
        await state.set_state("quiz:duration")
    else:
        validate_timing((await state.get_data())["interval"], value)
        await state.update_data(duration=value)
        await state.set_state("quiz:count")
    await show_step(message, state, db)


@router.callback_query(F.data.startswith("flow:"))
async def flow_navigation(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    current = await state.get_state()
    if not current or not current.startswith("quiz:"):
        raise UserError("Bu tugma eskirgan.")
    if call.data == "flow:cancel":
        await state.clear()
        await call.message.answer("Bekor qilindi.")
        return
    data = await state.get_data()
    back = {
        "place": "place",
        "chat": "place",
        "category": "place" if data.get("kind") == "private" else "chat",
        "interval": "category",
        "custom": "interval",
        "duration": "interval",
        "duration_custom": "duration",
        "count": "duration",
        "confirm": "count",
    }
    await state.set_state("quiz:" + back[current.split(":")[1]])
    await show_step(call.message, state, db)


@router.message(F.text == "➕ Guruh yoki kanalga ulash")
@router.message(Command("link"))
async def linking(message: Message, bot: Bot) -> None:
    await private_only(message)
    username = (await bot.me()).username
    await message.answer(
        "Chatni tanlang. Telegram siz va bot huquqlarini tekshiradi; bot ham qayta tekshiradi.",
        reply_markup=chat_picker(),
    )
    await message.answer(
        f"Qo‘lda ulash: https://t.me/{username}?startgroup=setup\n"
        f"Kanalga qo‘shish: https://t.me/{username}?startchannel&admin=post_messages\n"
        "Qo‘shgach /linkchat -100... orqali chat IDni yuborish ham mumkin."
    )


@router.message(F.chat_shared)
async def shared(message: Message, db: Database, bot: Bot, db_user: User) -> None:
    await private_only(message)
    chat = await link_chat(db, bot, message.from_user.id, message.chat_shared.chat_id)
    await message.answer(
        f"✅ {escape(chat.title)} ulandi. Endi Quiz boshlash menyusida sozlang.",
        reply_markup=menu(db_user.role != "user"),
    )


@router.message(Command("linkchat"))
async def link_command(message: Message, db: Database, bot: Bot) -> None:
    await private_only(message)
    try:
        chat_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        raise UserError("Namuna: /linkchat -1001234567890")
    chat = await link_chat(db, bot, message.from_user.id, chat_id)
    await message.answer(f"✅ {escape(chat.title)} ulandi.")


@router.message(F.text == "📊 Natijalarim")
@router.message(Command("results"))
async def my_results(message: Message, db: Database) -> None:
    await private_only(message)
    async with db.sessions() as tx:
        text = await personal(tx, message.from_user.id)
    parts = [""]
    for line in text.splitlines():
        if len(parts[-1]) + len(line) + 1 > 3500:
            parts.append("")
        parts[-1] += line + "\n"
    for part in parts:
        await message.answer(part)


@router.message(F.text.in_({"⚙️ Faol quizlarim", "🏆 Reyting"}))
@router.message(Command("sessions", "ranking"))
async def sessions(message: Message, db: Database) -> None:
    wants_ranking = (
        message.text == "🏆 Reyting" or message.text.split()[0].split("@")[0] == "/ranking"
    )
    async with db.sessions() as tx:
        query = select(QuizSession).order_by(QuizSession.id.desc()).limit(20)
        if message.chat.type == "private":
            query = query.where(
                (QuizSession.owner_id == message.from_user.id)
                | QuizSession.chat_id.in_(
                    select(ChatManager.chat_id).where(ChatManager.user_id == message.from_user.id)
                )
            )
        else:
            query = query.where(QuizSession.chat_id == message.chat.id)
        if message.text == "⚙️ Faol quizlarim":
            query = query.where(QuizSession.status.in_(["active", "paused", "stopping"]))
        rows = (await tx.scalars(query)).all()
    await message.answer(
        "Oxirgi sessiyalar:" if rows else "Sessiya yo‘q.",
        reply_markup=inline(
            [
                [
                    (
                        f"#{s.id} — {status_label(s.status)}",
                        f"rank:{s.id}:0" if wants_ranking else f"status:{s.id}",
                    )
                ]
                for s in rows
            ]
        ),
    )


async def session_access(
    tx: AsyncSession, bot: Bot, session_id: int, actor: int, settings: Settings
) -> QuizSession:
    s = await tx.get(QuizSession, session_id)
    if not s:
        raise UserError("Sessiya topilmadi.")
    await manage(bot, tx, s, actor, settings.superadmin_id)
    return s


@router.callback_query(F.data.startswith("status:"))
async def status(call: CallbackQuery, db: Database, bot: Bot, settings: Settings) -> None:
    async with db.sessions() as tx:
        s = await session_access(tx, bot, int(call.data.split(":")[1]), call.from_user.id, settings)
        when = (
            s.next_run_at.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m.%Y %H:%M:%S")
            if s.next_run_at
            else "—"
        )
        text = f"Quiz #{s.id}: {status_label(s.status)}\nYuborilgan: {s.sent}/{s.total or '∞'}\nInterval: {s.interval // 60} minut\nJavob: {s.duration} soniya\nNavbat: {when}\n{escape(s.reason or '')}"
    await call.message.answer(text, reply_markup=controls(s.id))


@router.callback_query(F.data.startswith("ctl:"))
async def control_callback(
    call: CallbackQuery, db: Database, bot: Bot, settings: Settings, scheduler: Scheduler
) -> None:
    _, sid, action = call.data.split(":")
    result = await control(db, bot, int(sid), call.from_user.id, action, settings.superadmin_id)
    scheduler.wake.set()
    await call.message.answer(f"Holat: {status_label(result)}", reply_markup=controls(int(sid)))


@router.message(Command("pause", "resume", "stop", "status", "settings"))
async def command_control(
    message: Message, db: Database, bot: Bot, settings: Settings, scheduler: Scheduler
) -> None:
    command = message.text.split()[0].split("@")[0][1:]
    parts = message.text.split()
    async with db.sessions() as tx:
        if len(parts) > 1 and parts[1].isdigit():
            s = await session_access(tx, bot, int(parts[1]), message.from_user.id, settings)
        else:
            s = await tx.scalar(
                select(QuizSession).where(
                    QuizSession.chat_id == message.chat.id,
                    QuizSession.status.in_(["active", "paused", "stopping"]),
                )
            )
            if not s:
                raise UserError("Faol sessiya yo‘q. Yoki commanddan keyin sessiya IDni yozing.")
            await manage(bot, tx, s, message.from_user.id, settings.superadmin_id)
    if command in {"status", "settings"}:
        await message.answer(
            f"#{s.id} {status_label(s.status)} | {s.sent}/{s.total or '∞'}\nInterval {s.interval // 60} minut, javob {s.duration} soniya.\nSozlamalarni o‘zgartirish uchun sessiyani to‘xtatib, yangi quiz yarating.",
            reply_markup=controls(s.id),
        )
    else:
        result = await control(db, bot, s.id, message.from_user.id, command, settings.superadmin_id)
        scheduler.wake.set()
        await message.answer(f"Holat: {status_label(result)}")


@router.callback_query(F.data.startswith("rank:"))
async def ranks(call: CallbackQuery, db: Database, bot: Bot, settings: Settings) -> None:
    _, sid, p = call.data.split(":")
    page = max(0, int(p))
    async with db.sessions() as tx:
        s = await tx.get(QuizSession, int(sid))
        if not s:
            raise UserError("Sessiya topilmadi.")
        chat = await tx.get(Chat, s.chat_id)
        if chat.kind == "private" or call.message.chat.id != chat.id:
            await manage(bot, tx, s, call.from_user.id, settings.superadmin_id)
        if chat.kind == "channel":
            questions = (
                await tx.scalars(select(SessionQuestion).where(SessionQuestion.session_id == s.id))
            ).all()
            total = sum(q.aggregate.get("total", 0) for q in questions)
            await call.message.answer(f"Kanal: {total} anonim ovoz. Individual reyting tuzilmaydi.")
            return
        rows = await ranking(tx, session_id=s.id)
        page = min(page, max(0, (len(rows) - 1) // 10))
    buttons = []
    if page:
        buttons.append(("⬅️", f"rank:{sid}:{page - 1}"))
    if (page + 1) * 10 < len(rows):
        buttons.append(("➡️", f"rank:{sid}:{page + 1}"))
    await call.message.answer(
        f"🏆 Sessiya #{sid}\n"
        + format_ranks(rows, page)
        + "\nVaqt — bot kuzatgan taxminiy davomiylik.",
        reply_markup=inline([buttons]) if buttons else None,
    )


@router.callback_query(F.data.startswith("people:"))
async def people(call: CallbackQuery, db: Database, bot: Bot, settings: Settings) -> None:
    _, sid, p = call.data.split(":")
    page = max(0, int(p))
    async with db.sessions() as tx:
        s = await session_access(tx, bot, int(sid), call.from_user.id, settings)
        rows = await ranking(tx, session_id=s.id)
    buttons = [
        [(r.name[:40], f"detail:{sid}:{r.user_id}:0")] for r in rows[page * 10 : (page + 1) * 10]
    ]
    if page:
        buttons.append([("⬅️", f"people:{sid}:{page - 1}")])
    if (page + 1) * 10 < len(rows):
        buttons.append([("➡️", f"people:{sid}:{page + 1}")])
    await call.message.answer(
        "Qatnashchini tanlang:" if rows else "Javoblar yo‘q.", reply_markup=inline(buttons)
    )


@router.callback_query(F.data.startswith("detail:"))
async def detail(call: CallbackQuery, db: Database, bot: Bot, settings: Settings) -> None:
    _, sid, uid, p = call.data.split(":")
    page = max(0, int(p))
    async with db.sessions() as tx:
        await session_access(tx, bot, int(sid), call.from_user.id, settings)
        rows = (
            await tx.execute(
                select(SessionQuestion, Answer)
                .outerjoin(
                    Answer,
                    (Answer.session_question_id == SessionQuestion.id)
                    & (Answer.user_id == int(uid)),
                )
                .where(
                    SessionQuestion.session_id == int(sid),
                    SessionQuestion.status.in_(["open", "closed"]),
                )
                .order_by(SessionQuestion.id)
                .offset(page * 5)
                .limit(6)
            )
        ).all()
    lines = []
    for q, a in rows[:5]:
        value = (
            q.snapshot["options"][a.option]
            if a and a.option is not None
            else "Javob yo‘q / qaytarib olingan"
        )
        lines.append(
            f"{escape(q.snapshot['text'])}\nTanlov: {escape(value)}\nBall: {a.points if a else 0}"
        )
    buttons = []
    if page:
        buttons.append(("⬅️", f"detail:{sid}:{uid}:{page - 1}"))
    if len(rows) > 5:
        buttons.append(("➡️", f"detail:{sid}:{uid}:{page + 1}"))
    await call.message.answer(
        "\n\n".join(lines) or "Javoblar yo‘q.", reply_markup=inline([buttons]) if buttons else None
    )


@router.message(F.text == "ℹ️ Yordam")
@router.message(Command("help"))
async def help_message(message: Message) -> None:
    await message.answer(
        "Quiz boshlash → joy → kategoriya → interval → javob muddati → son → tasdiqlash.\n"
        "Guruh/kanalni avval ulang. Ularni Telegram administratori boshqaradi.\n"
        "/quiz /sessions /results /ranking\n/pause /resume /stop /status /settings [sessiya ID]\n"
        "/cancel — jarayonni bekor qilish.\nTo‘g‘ri javob 1 ball. Teng ball: to‘g‘ri javoblarning kuzatilgan jami vaqti, keyin user ID.\n"
        "Kanal ovozlari anonim; shaxsiy natija uchun poll ostidagi havolaga o‘ting."
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Jarayon bekor qilindi.")


@router.message(Command("chatranking"))
async def chat_ranking_command(message: Message, db: Database) -> None:
    await show_chat_ranking(message, db, message.chat.id, 0)


async def show_chat_ranking(message: Message, db: Database, chat_id: int, page: int) -> None:
    async with db.sessions() as tx:
        chat = await tx.get(Chat, chat_id)
        if not chat or chat.kind == "channel":
            raise UserError("Bu chat uchun individual reyting mavjud emas.")
        rows = await ranking(tx, chat_id=chat_id)
    page = min(max(0, page), max(0, (len(rows) - 1) // 10))
    buttons = []
    if page:
        buttons.append(("⬅️", f"chatrank:{chat_id}:{page - 1}"))
    if (page + 1) * 10 < len(rows):
        buttons.append(("➡️", f"chatrank:{chat_id}:{page + 1}"))
    await message.answer(
        "🏆 Shu chat bo‘yicha reyting\n" + format_ranks(rows, page),
        reply_markup=inline([buttons]) if buttons else None,
    )


@router.callback_query(F.data.startswith("chatrank:"))
async def chat_ranking_callback(call: CallbackQuery, db: Database) -> None:
    _, cid, page = call.data.split(":")
    if int(cid) != call.message.chat.id:
        raise UserError("Reytingni tegishli chatda oching.")
    if call.message.chat.type == "private" and call.from_user.id != int(cid):
        raise UserError("Bu shaxsiy reyting sizga tegishli emas.")
    await show_chat_ranking(call.message, db, int(cid), int(page))


@router.callback_query()
async def stale_callback(call: CallbackQuery) -> None:
    await call.message.answer(
        "Bu tugma eskirgan yoki sizda amal uchun huquq yo‘q. /start orqali menyuni oching."
    )


@router.message()
async def unknown_message(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current:
        await message.answer(
            "Joriy bosqichdagi tugmadan foydalaning yoki so‘ralgan qiymatni kiriting. Bekor qilish: /cancel"
        )
    else:
        await message.answer("Menyuni ochish uchun /start yozing.")
