import asyncio
import logging

from telethon import TelegramClient

from bot.handlers import register_handlers
from config import API_HASH, API_ID, BOT_TOKEN
from database import init_db
from userbot.manager import UserbotManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    init_db()

    bot_client = TelegramClient("bot_session", API_ID, API_HASH)
    await bot_client.start(bot_token=BOT_TOKEN)

    manager = UserbotManager(bot_client)
    register_handlers(bot_client, manager)

    await manager.start_all()

    logger.info("Bot ishga tushdi.")
    await bot_client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
