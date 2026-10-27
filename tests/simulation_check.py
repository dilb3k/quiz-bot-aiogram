"""Real Aiogram HTTP client against the local Postman simulation; no live token."""

import asyncio
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramServerError
from aiogram.types import InputPollOption


async def main() -> None:
    api = TelegramAPIServer.from_base("http://127.0.0.1:4900/telegram")
    async with Bot(
        "123456:LOCAL_SIMULATION_ONLY", session=AiohttpSession(api=api, timeout=5)
    ) as bot:
        kwargs = dict(
            question="2 + 2?",
            options=[InputPollOption(text="4"), InputPollOption(text="5")],
            type="quiz",
            is_anonymous=False,
            correct_option_ids=[0],
            open_period=30,
            allows_revoting=False,
        )
        msg = await bot.send_poll(1, **kwargs)
        assert msg.poll.type == "quiz" and not msg.poll.is_anonymous
        closed = await bot.stop_poll(1, msg.message_id)
        assert closed.is_closed
        for chat_id, error in [
            (-429, TelegramRetryAfter),
            (-403, TelegramForbiddenError),
            (-500, TelegramServerError),
        ]:
            try:
                await bot.send_poll(chat_id, **kwargs)
            except error as exc:
                if chat_id == -429:
                    assert exc.retry_after == 2
            else:
                raise AssertionError(f"Expected {error.__name__}")
        print("Aiogram HTTP: sendPoll, stopPoll, 429, 403, 500 passed")


if __name__ == "__main__":
    asyncio.run(main())
