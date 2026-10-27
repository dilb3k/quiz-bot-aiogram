from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButtonRequestChat,
    ChatAdministratorRights,
)


def inline(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
        ]
    )


def menu(admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        ["🧠 Quiz boshlash", "📊 Natijalarim"],
        ["🏆 Reyting", "⚙️ Faol quizlarim"],
        ["➕ Guruh yoki kanalga ulash", "ℹ️ Yordam"],
    ]
    if admin:
        rows.append(["🛠 Admin panel"])
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows], resize_keyboard=True
    )


def navigation() -> list[list[tuple[str, str]]]:
    return [[("⬅️ Orqaga", "flow:back"), ("Bekor qilish", "flow:cancel")]]


def controls(session_id: int) -> InlineKeyboardMarkup:
    return inline(
        [
            [
                ("⏸ Pauza", f"ctl:{session_id}:pause"),
                ("▶️ Davom ettirish", f"ctl:{session_id}:resume"),
            ],
            [("⏹ To‘xtatish", f"ctl:{session_id}:stop")],
            [
                ("⚙️ Sozlamalar / holat", f"status:{session_id}"),
                ("🏆 Reyting", f"rank:{session_id}:0"),
            ],
            [("👤 Qatnashchi javoblari", f"people:{session_id}:0")],
        ]
    )


def chat_picker() -> ReplyKeyboardMarkup:
    def rights(channel: bool) -> ChatAdministratorRights:
        return ChatAdministratorRights(
            is_anonymous=False,
            can_send_welcome_messages=False,
            can_manage_chat=True,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
            can_post_messages=True if channel else None,
        )

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Guruhni tanlash",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=1,
                        chat_is_channel=False,
                        user_administrator_rights=rights(False),
                        bot_administrator_rights=rights(False),
                        request_title=True,
                    ),
                )
            ],
            [
                KeyboardButton(
                    text="Kanalni tanlash",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=2,
                        chat_is_channel=True,
                        user_administrator_rights=rights(True),
                        bot_administrator_rights=rights(True),
                        request_title=True,
                    ),
                )
            ],
            [KeyboardButton(text="/start")],
        ],
        resize_keyboard=True,
    )
