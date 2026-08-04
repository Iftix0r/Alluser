import asyncio
import fcntl
import logging
import sys

from telethon import TelegramClient

from bot.admin_handlers import register_admin_handlers
from bot.handlers import register_handlers
from config import API_HASH, API_ID, BOT_TOKEN
from database import init_db
from userbot.manager import UserbotManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

LOCK_PATH = "aluser.lock"
SUBSCRIPTION_SWEEP_INTERVAL_SECONDS = 3600
AD_BROADCAST_CHECK_INTERVAL_SECONDS = 60


def acquire_single_instance_lock():
    """Bot bir vaqtning o'zida faqat bitta nusxada ishlashini ta'minlaydi.

    Bir nechta nusxa bir xil BOT_TOKEN bilan ulansa, Telegram MTProto
    yangilanishlarni har ikkalasiga ham yuborishi mumkin — natijada har bir
    xabar/buyruq ikki (yoki undan ko'p) marta ishlov olib, foydalanuvchiga
    takrorlangan javoblar ketadi.
    """
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error(
            "Bot allaqachon boshqa jarayonda ishlamoqda (%s qulflangan). "
            "Avvalgi nusxani to'xtating va qaytadan urinib ko'ring.",
            LOCK_PATH,
        )
        sys.exit(1)
    return lock_file


async def subscription_sweep_loop(manager: UserbotManager) -> None:
    while True:
        await asyncio.sleep(SUBSCRIPTION_SWEEP_INTERVAL_SECONDS)
        try:
            await manager.sweep_expired_subscriptions()
        except Exception:
            logger.exception("Obuna tekshiruvida xatolik")


async def ad_broadcast_loop(manager: UserbotManager) -> None:
    while True:
        await asyncio.sleep(AD_BROADCAST_CHECK_INTERVAL_SECONDS)
        try:
            await manager.run_ad_broadcast_cycle()
        except Exception:
            logger.exception("Reklama yuborish tsiklida xatolik")


async def main() -> None:
    lock_file = acquire_single_instance_lock()

    init_db()

    bot_client = TelegramClient("bot_session", API_ID, API_HASH)
    await bot_client.start(bot_token=BOT_TOKEN)
    bot_username = (await bot_client.get_me()).username

    manager = UserbotManager(bot_client)
    register_handlers(bot_client, manager, bot_username)
    register_admin_handlers(bot_client, manager)

    await manager.start_all()

    sweep_task = asyncio.create_task(subscription_sweep_loop(manager))
    ad_task = asyncio.create_task(ad_broadcast_loop(manager))

    logger.info("Bot ishga tushdi.")
    try:
        await bot_client.run_until_disconnected()
    finally:
        logger.info("Bot to'xtatilmoqda, userbot klientlari uzilmoqda...")
        sweep_task.cancel()
        ad_task.cancel()
        for user_db_id in list(manager.clients):
            await manager.stop_client_for_user(user_db_id)
        lock_file.close()


if __name__ == "__main__":
    asyncio.run(main())
