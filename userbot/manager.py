import asyncio
import logging
import time
from collections import deque

from telethon import TelegramClient, events
from telethon.errors import RPCError
from telethon.sessions import StringSession

import db_utils
from config import API_HASH, API_ID
from matcher import extract_phone, find_matched_keyword

logger = logging.getLogger(__name__)

RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60


class UserbotManager:
    """Har bir ulangan foydalanuvchi uchun alohida Telethon user-client boshqaradi."""

    def __init__(self, bot_client: TelegramClient):
        self.bot_client = bot_client
        self.clients: dict[int, TelegramClient] = {}
        self._forward_times: dict[int, deque] = {}

    def _rate_limited(self, user_db_id: int) -> bool:
        now = time.monotonic()
        times = self._forward_times.setdefault(user_db_id, deque())
        while times and now - times[0] > RATE_LIMIT_WINDOW_SECONDS:
            times.popleft()
        if len(times) >= RATE_LIMIT_COUNT:
            return True
        times.append(now)
        return False

    async def start_client_for_user(self, user) -> bool:
        if user.id in self.clients:
            return True

        client = TelegramClient(StringSession(user.session_string), API_ID, API_HASH)
        try:
            await client.connect()
        except RPCError:
            logger.exception("Foydalanuvchi %s uchun ulanib bo'lmadi", user.tg_user_id)
            return False

        if not await client.is_user_authorized():
            logger.warning("Foydalanuvchi %s sessiyasi yaroqsiz", user.tg_user_id)
            await client.disconnect()
            db_utils.clear_session(user.tg_user_id)
            await self._notify(
                user.tg_user_id,
                "⚠️ Akkaunt sessiyasi tugagan yoki bekor qilingan. Iltimos, /start orqali qayta ulang.",
            )
            return False

        user_db_id = user.id
        tg_user_id = user.tg_user_id

        @client.on(events.NewMessage(incoming=True))
        async def handler(event, user_db_id=user_db_id, tg_user_id=tg_user_id):
            await self._handle_message(event, user_db_id, tg_user_id)

        self.clients[user.id] = client
        logger.info("Userbot ishga tushdi: tg_user_id=%s", tg_user_id)
        return True

    async def stop_client_for_user(self, user_db_id: int) -> None:
        client = self.clients.pop(user_db_id, None)
        self._forward_times.pop(user_db_id, None)
        if client:
            await client.disconnect()

    async def start_all(self) -> None:
        for user in db_utils.get_active_users():
            await self.start_client_for_user(user)

    async def _notify(self, tg_user_id: int, text: str) -> None:
        try:
            await self.bot_client.send_message(tg_user_id, text)
        except RPCError:
            logger.warning("Foydalanuvchiga xabar yuborib bo'lmadi: %s", tg_user_id)

    async def _handle_message(self, event, user_db_id: int, tg_user_id: int) -> None:
        if event.out or not event.is_group:
            return

        current = await asyncio.to_thread(db_utils.find_user_by_id, user_db_id)
        if not current or not current.is_active or not current.order_group_id:
            return

        excluded = await asyncio.to_thread(db_utils.get_excluded_group_ids, user_db_id)
        if event.chat_id in excluded:
            return

        keywords = await asyncio.to_thread(db_utils.list_keywords, tg_user_id)
        if not keywords:
            return

        text = event.raw_text or ""
        matched = find_matched_keyword(text, keywords)
        if not matched:
            return

        if self._rate_limited(user_db_id):
            logger.info("Rate limit: user=%s xabar o'tkazib yuborildi", tg_user_id)
            return

        sender = await event.get_sender()
        if getattr(sender, "bot", False):
            return

        name = " ".join(
            filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])
        ) or "Noma'lum"
        username = f"@{sender.username}" if getattr(sender, "username", None) else "yo'q"
        phone = extract_phone(text) or "topilmadi"

        chat = await event.get_chat()
        chat_title = getattr(chat, "title", "Noma'lum guruh")
        chat_username = getattr(chat, "username", None)

        message_lines = [
            "🚕 Yangi buyurtma!",
            "",
            f"🔑 Kalit so'z: {matched}",
            f"👤 Ism: {name}",
            f"🔗 Username: {username}",
            f"📞 Telefon: {phone}",
            f"📍 Guruh: {chat_title}",
            f"🕒 Vaqt: {event.message.date.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
        if chat_username:
            message_lines.append(f"🔗 Xabar: https://t.me/{chat_username}/{event.id}")
        message_lines.append(f"👤 Profil: tg://user?id={sender.id}")
        message_lines.append("")
        message_lines.append(f"💬 Xabar:\n{text}")
        message = "\n".join(message_lines)

        try:
            await self.bot_client.send_message(current.order_group_id, message, link_preview=False)
        except RPCError:
            logger.exception("Buyurtma guruhga yuborilmadi: user=%s", tg_user_id)
            await self._notify(
                tg_user_id,
                "⚠️ Buyurtmani buyurtma guruhga yubora olmadim. Bot o'sha guruhda a'zoligini tekshiring.",
            )
