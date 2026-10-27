import unittest
from aiogram.methods import SendPoll
from aiogram.types import InputPollOption, PollAnswer, User
from quizbot.keyboards.common import menu, chat_picker, controls


class ContractTests(unittest.TestCase):
    def test_native_quiz_payload(self):
        method = SendPoll(
            chat_id=1,
            question="Test?",
            options=[InputPollOption(text="A"), InputPollOption(text="B")],
            type="quiz",
            is_anonymous=False,
            allows_multiple_answers=False,
            allows_revoting=False,
            correct_option_ids=[1],
            open_period=30,
        )
        payload = method.model_dump(exclude_none=True)
        self.assertEqual(payload["correct_option_ids"], [1])
        self.assertFalse(payload["is_anonymous"])

    def test_withdrawal_update_model(self):
        answer = PollAnswer(
            poll_id="test",
            option_ids=[],
            option_persistent_ids=[],
            user=User(id=1, is_bot=False, first_name="Ali"),
        )
        self.assertEqual(answer.option_ids, [])
        self.assertIsNone(answer.voter_chat)

    def test_menu_role(self):
        self.assertEqual(len(menu(True).keyboard), 4)
        self.assertEqual(len(menu(False).keyboard), 3)

    def test_chat_selection_rights(self):
        kb = chat_picker()
        channel = kb.keyboard[1][0].request_chat
        self.assertTrue(channel.chat_is_channel)
        self.assertTrue(channel.bot_administrator_rights.can_post_messages)
        self.assertTrue(channel.user_administrator_rights.can_post_messages)

    def test_callback_limits(self):
        for row in controls(2147483647).inline_keyboard:
            for button in row:
                self.assertLessEqual(len(button.callback_data.encode()), 64)
