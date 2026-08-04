import asyncio
import html
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from telethon import TelegramClient, events, utils
from telethon.errors import RPCError
from telethon.helpers import add_surrogate
from telethon.sessions import StringSession
from telethon.tl.custom import Button
from telethon.tl.types import InputMessageEntityMentionName

import db_utils
from config import API_HASH, API_ID
from crypto_utils import decrypt_session
from matcher import extract_phone, find_matched_keyword, has_meaningful_text, is_valid_order_text

logger = logging.getLogger(__name__)

RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60

CATCHUP_ORDER_LIMIT = 20
CATCHUP_MESSAGES_PER_GROUP = 30
CATCHUP_LOOKBACK_HOURS = 12
CATCHUP_DIALOG_LIMIT = 200

AD_SEND_DELAY_SECONDS = 3


class UserbotManager:
    """Har bir ulangan foydalanuvchi uchun alohida Telethon user-client boshqaradi."""

    def __init__(self, bot_client: TelegramClient):
        self.bot_client = bot_client
        self.clients: dict[int, TelegramClient] = {}
        self._forward_times: dict[int, deque] = {}
        self.claims: dict[tuple[int, int], str] = {}

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

        try:
            session_str = decrypt_session(user.session_string)
        except InvalidToken:
            logger.error("Foydalanuvchi %s sessiya shifrini ochib bo'lmadi", user.tg_user_id)
            db_utils.clear_session(user.tg_user_id)
            await self.notify(
                user.tg_user_id,
                "⚠️ Akkaunt sessiyasi buzilgan. Iltimos, /start orqali qayta ulang.",
            )
            return False

        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        try:
            await client.connect()
        except RPCError:
            logger.exception("Foydalanuvchi %s uchun ulanib bo'lmadi", user.tg_user_id)
            return False

        if not await client.is_user_authorized():
            logger.warning("Foydalanuvchi %s sessiyasi yaroqsiz", user.tg_user_id)
            await client.disconnect()
            db_utils.clear_session(user.tg_user_id)
            await self.notify(
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
            started = await self.start_client_for_user(user)
            if started:
                try:
                    await self._catch_up_missed_orders(user)
                except Exception:
                    logger.exception(
                        "Qolib ketgan buyurtmalarni qidirishda xatolik: user=%s", user.tg_user_id
                    )

    async def sweep_expired_subscriptions(self) -> None:
        """Obunasi tugagan foydalanuvchilarni to'xtatadi va xabar beradi."""
        for user in await asyncio.to_thread(db_utils.get_expired_active_users):
            db_utils.toggle_active(user.tg_user_id, False)
            await self.stop_client_for_user(user.id)
            await self.notify(
                user.tg_user_id,
                "⛔ Obunangiz muddati tugadi, kuzatish to'xtatildi. Davom ettirish uchun "
                "admin bilan bog'lanib to'lovni amalga oshiring.",
            )
            logger.info("Obuna tugadi, to'xtatildi: tg_user_id=%s", user.tg_user_id)

    async def _send_ad_to_groups(self, user, settings, target_ids: set[int]) -> int:
        client = self.clients.get(user.id)
        if not client:
            return 0
        sent = 0
        for chat_id in target_ids:
            try:
                await client.send_message(chat_id, settings.text, link_preview=False)
                sent += 1
            except RPCError:
                logger.warning("Reklama yuborilmadi: user=%s, chat=%s", user.tg_user_id, chat_id)
            except Exception:
                logger.exception(
                    "Reklama yuborishda kutilmagan xatolik: user=%s, chat=%s", user.tg_user_id, chat_id
                )
            await asyncio.sleep(AD_SEND_DELAY_SECONDS)
        if sent:
            await asyncio.to_thread(db_utils.update_ad_last_sent, user.id, datetime.utcnow())
        return sent

    async def run_ad_broadcast_cycle(self) -> None:
        """Belgilangan intervalda reklama matnini foydalanuvchi tanlagan guruhlarga yuboradi."""
        now = datetime.utcnow()
        for user in await asyncio.to_thread(db_utils.get_users_with_active_ads):
            if not self.clients.get(user.id):
                continue
            if not db_utils.is_subscription_active(user):
                continue
            settings = await asyncio.to_thread(db_utils.get_ad_settings, user.tg_user_id)
            if not settings or not settings.is_active or not settings.text:
                continue
            if settings.last_sent_at and now - settings.last_sent_at < timedelta(minutes=settings.interval_minutes):
                continue
            target_ids = await asyncio.to_thread(db_utils.get_ad_target_group_ids, user.id)
            if not target_ids:
                continue
            await self._send_ad_to_groups(user, settings, target_ids)

    async def send_ad_now(self, user_db_id: int) -> int | None:
        """Reklamani darhol yuboradi (test/qo'lda). Yuborilgan guruhlar sonini qaytaradi,
        sozlamalar to'liq bo'lmasa None."""
        user = await asyncio.to_thread(db_utils.find_user_by_id, user_db_id)
        if not user or not self.clients.get(user_db_id):
            return None
        settings = await asyncio.to_thread(db_utils.get_ad_settings, user.tg_user_id)
        if not settings or not settings.text:
            return None
        target_ids = await asyncio.to_thread(db_utils.get_ad_target_group_ids, user_db_id)
        if not target_ids:
            return None
        return await self._send_ad_to_groups(user, settings, target_ids)

    async def notify(self, tg_user_id: int, text: str) -> None:
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

        if not db_utils.is_subscription_active(current):
            return

        excluded = await asyncio.to_thread(db_utils.get_excluded_group_ids, user_db_id)
        keywords = await asyncio.to_thread(db_utils.list_keywords, tg_user_id)
        driver_keywords = await asyncio.to_thread(db_utils.list_driver_keywords, tg_user_id)

        await self._process_message(event, current, keywords, driver_keywords, excluded)

    async def _catch_up_missed_orders(self, user) -> None:
        """Bot qayta ishga tushganda, oflayn bo'lgan vaqtda kelib qolib ketgan buyurtmalarni
        guruhlar tarixidan topib, buyurtma guruhga yuboradi (eng ko'pi bilan
        CATCHUP_ORDER_LIMIT ta, eng yangilaridan boshlab)."""
        client = self.clients.get(user.id)
        if not client or not user.is_active or not user.order_group_id:
            return

        if not db_utils.is_subscription_active(user):
            return

        keywords = await asyncio.to_thread(db_utils.list_keywords, user.tg_user_id)
        if not keywords:
            return

        driver_keywords = await asyncio.to_thread(db_utils.list_driver_keywords, user.tg_user_id)
        excluded = await asyncio.to_thread(db_utils.get_excluded_group_ids, user.id)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=CATCHUP_LOOKBACK_HOURS)

        candidates = []
        async for dialog in client.iter_dialogs(limit=CATCHUP_DIALOG_LIMIT):
            if not dialog.is_group or dialog.id in excluded:
                continue
            try:
                async for message in client.iter_messages(dialog.id, limit=CATCHUP_MESSAGES_PER_GROUP):
                    if message.date < cutoff:
                        break
                    candidates.append(message)
            except RPCError:
                logger.warning(
                    "Guruh tarixini o'qib bo'lmadi: chat=%s, user=%s", dialog.id, user.tg_user_id
                )
                continue

        if not candidates:
            return

        candidates.sort(key=lambda m: m.date)

        sent = 0
        for message in candidates:
            current = await asyncio.to_thread(db_utils.find_user_by_id, user.id)
            if not current or not current.is_active or not current.order_group_id:
                break
            if not db_utils.is_subscription_active(current):
                break
            ok = await self._process_message(message, current, keywords, driver_keywords, excluded)
            if ok:
                sent += 1
                if sent >= CATCHUP_ORDER_LIMIT:
                    break

        if sent:
            logger.info("Qolib ketgan %s ta buyurtma topib yuborildi: user=%s", sent, user.tg_user_id)

    async def _process_message(self, message, current, keywords, driver_keywords, excluded) -> bool:
        """`message` — NewMessage eventi yoki client.iter_messages() dan kelgan Message.
        Mos kelsa, buyurtmani buyurtma guruhga yuborib True qaytaradi."""
        if message.out or not message.is_group:
            return False

        if message.chat_id in excluded:
            return False

        if message.sticker:
            return False

        text = message.raw_text or ""
        if not is_valid_order_text(text):
            return False

        if driver_keywords and find_matched_keyword(text, driver_keywords):
            return False

        matched = find_matched_keyword(text, keywords)
        if not matched:
            if (
                not current.assume_passenger_if_unmatched
                or not has_meaningful_text(text)
                or message.media
            ):
                return False
            matched = "aniqlanmagan (yo'lovchi deb qabul qilindi)"

        sender = await message.get_sender()
        if getattr(sender, "bot", False):
            return False

        blocked = await asyncio.to_thread(db_utils.is_sender_blocked, current.id, sender.id)
        if blocked:
            return False

        if self._rate_limited(current.id):
            logger.info("Rate limit: user=%s xabar o'tkazib yuborildi", current.tg_user_id)
            return False

        name = " ".join(
            filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])
        )
        username = f"@{sender.username}" if getattr(sender, "username", None) else None
        phone = extract_phone(text)

        chat = await message.get_chat()
        chat_title = getattr(chat, "title", None)
        chat_username = getattr(chat, "username", None)

        fields = [f"🔑 Kalit so'z: {html.escape(matched)}"]
        if name:
            fields.append(f"👤 Ism: {html.escape(name)}")
        if username:
            fields.append(f"🔗 Username: {html.escape(username)}")
        if phone:
            fields.append(f"📞 Telefon: {html.escape(phone)}")
        if chat_title and not chat_username:
            fields.append(f"📍 Guruh: {html.escape(chat_title)}")

        message_lines = ["🚕 Yangi buyurtma!", ""]
        for field in fields:
            message_lines += [field, ""]
        message_lines.append(f"💬 Xabar:\n<b><i>{html.escape(text)}</i></b>")
        order_text = "\n".join(message_lines)

        group_row = []
        if chat_username:
            group_row.append(Button.url(f"📍 {chat_title or 'Guruh'}", f"https://t.me/{chat_username}"))
        link_row = []
        if chat_username:
            link_row.append(Button.url("🔗 Xabarga o'tish", f"https://t.me/{chat_username}/{message.id}"))
        link_row.append(Button.url("👤 Profil", f"tg://user?id={sender.id}"))
        buttons = [
            *([group_row] if group_row else []),
            link_row,
            [Button.inline("🚫 Bloklash", f"block:{sender.id}:{current.id}".encode())],
        ]

        try:
            await self.bot_client.send_message(
                current.order_group_id, order_text, buttons=buttons, link_preview=False, parse_mode="html"
            )
        except RPCError:
            logger.exception("Buyurtma guruhga yuborilmadi: user=%s", current.tg_user_id)
            await self.notify(
                current.tg_user_id,
                "⚠️ Buyurtmani buyurtma guruhga yubora olmadim. Bot o'sha guruhda a'zoligini tekshiring.",
            )
            return False

        # Bot mijozni to'g'ridan-to'g'ri mention qila olmaydi (u bilan aloqada bo'lmagani
        # uchun access_hash yo'q). Akkaunt esa mijoz turgan guruhda a'zo bo'lgani uchun
        # haqiqiy bosiladigan mention yubora oladi.
        prefix = "👤 Mijoz: "
        mention_text = prefix + name
        try:
            input_user = utils.get_input_user(sender)
            offset = len(add_surrogate(prefix))
            length = len(add_surrogate(name))
            await message.client.send_message(
                current.order_group_id,
                mention_text,
                formatting_entities=[
                    InputMessageEntityMentionName(offset=offset, length=length, user_id=input_user)
                ],
            )
        except RPCError:
            logger.warning("Mijoz mention xabari yuborilmadi: user=%s", current.tg_user_id)

        return True
