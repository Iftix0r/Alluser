import asyncio
import html
import logging
import random
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError, RPCError, UserAlreadyParticipantError
from telethon.helpers import add_surrogate
from telethon.sessions import StringSession
from telethon.tl.custom import Button
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputMessageEntityMentionName

import db_utils
from config import ADMIN_CONTACT_ID, API_HASH, API_ID, SENDER_COOLDOWN_SECONDS
from crypto_utils import decrypt_session
from matcher import (
    extract_phone,
    extract_route,
    find_matched_keyword,
    has_emoji,
    has_meaningful_text,
    is_valid_order_text,
)

APK_MIME_TYPES = {"application/vnd.android.package-archive"}


def _is_apk_message(message) -> bool:
    """Xabarda APK fayl (yoki APK nomli fayl) bor-yo'qligini tekshiradi —
    zararli/virusli APK fayllardan himoyalanish uchun."""
    doc = getattr(message, "document", None)
    if not doc:
        return False
    if getattr(doc, "mime_type", None) in APK_MIME_TYPES:
        return True
    for attr in getattr(doc, "attributes", None) or []:
        filename = getattr(attr, "file_name", None)
        if filename and filename.lower().endswith(".apk"):
            return True
    return False

logger = logging.getLogger(__name__)

RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_SECONDS = 60

CATCHUP_ORDER_LIMIT = 20
CATCHUP_MESSAGES_PER_GROUP = 30
CATCHUP_LOOKBACK_HOURS = 12
CATCHUP_DIALOG_LIMIT = 200

AD_SEND_DELAY_SECONDS = 3
DEAD_AD_GROUP_FAILURE_THRESHOLD = 3

DEFAULT_GREETING_TEMPLATE = (
    "Assalomu alaykum! 👋\n\n"
    "Menga murojaat qilganingizdan judayam xursandman. Imkon qadar tezroq javob "
    "berishga harakat qilaman, lekin agar biroz band bo'lsam, ozgina sabr qilishingizni "
    "so'rayman — sizning xabaringiz men uchun muhim.\n\n"
    "Savolingiz, taklifingiz yoki buyurtmangiz bo'lsa, bemalol yozavering, albatta "
    "ko'rib chiqib, imkon qadar tezroq javob beraman.\n\n"
    "Ishlaringizga omad va yaxshi kunlar tilayman! 🙏\n\n"
    "—\n"
    "🤖 Ushbu xabar avtomatik yuborildi. Siz ham o'z biznesingiz uchun shunga o'xshash "
    "xizmatni sozlamoqchi bo'lsangiz: @{bot_username}"
)

DEFAULT_CUSTOMER_GREETING_TEMPLATE = (
    "Assalomu alaykum! 👋\n\n"
    "Guruhdagi xabaringizni ko'rdim va sizga yordam bera olishimni o'ylab, shaxsan "
    "murojaat qilishga qaror qildim.\n\n"
    "Savolingiz yoki buyurtmangiz bo'yicha batafsil yozib yuborsangiz, imkon qadar "
    "tezroq javob beraman va kerakli yordamni ko'rsataman.\n\n"
    "Ishonch bilan murojaat qilavering — vaqtingizni qadrlayman! 🙏\n\n"
    "—\n"
    "🤖 Ushbu xabar avtomatik yuborildi. @{bot_username}"
)

# Guruhda mijoz deb aniqlangan odamga shaxsiy DM yuborish — bu birinchi murojaat
# (odam hali yozmagan), shuning uchun spam xavfi yuqoriroq. Soatiga atigi 1-2 ta
# avtomatik yuboriladi, qolganlari uchun xo'jayindan Ha/Yo'q so'raladi.
CUSTOMER_DM_RATE_LIMIT_COUNT = 2
CUSTOMER_DM_RATE_LIMIT_WINDOW_SECONDS = 3600

# Tasdiqlash kutayotgan so'rovlar juda ko'payib ketmasligi uchun chegara.
MAX_PENDING_CUSTOMER_GREETINGS = 200

# Buyurtma kartasidagi "⚙️ Amallar" tugmasi orqali kutilayotgan amallar soni chegarasi.
MAX_PENDING_ORDER_ACTIONS = 500

RENEWAL_REMINDER_DAYS = 3

# Obuna tugashiga oz qolganda, foydalanuvchining O'Z akkountidan adminga yuboriladigan
# xabar — turlicha bo'lishi uchun bir nechtasidan tasodifiy tanlanadi.
RENEWAL_REQUEST_TEMPLATES = [
    (
        "Assalomu alaykum!\n\n"
        "Xizmatimdagi obunam {days} kundan so'ng tugar ekan. Ishimni to'xtatmasdan davom "
        "ettirish uchun hisobimni to'ldirib, obunani uzaytirishni xohlayman.\n\n"
        "Qachon va qanday to'lov qila olishim mumkinligini aytib bera olasizmi? Rahmat! 🙏"
    ),
    (
        "Salom!\n\n"
        "Obunam muddati {days} kunda tugaydi degan xabarni ko'rdim. Xizmatdan juda "
        "mamnunman, shuning uchun hisobimni to'ldirib, davom ettirmoqchiman.\n\n"
        "To'lov bo'yicha qanday yo'l bilan davom etsam bo'ladi?"
    ),
    (
        "Assalomu alaykum, hurmatli!\n\n"
        "Menga xizmat ko'rsatayotgan obunaning muddati {days} kundan keyin tugar ekan. "
        "Uzoq muddatga davom etmoqchiman, shuning uchun hisobni to'ldirishni xohlayman.\n\n"
        "Iltimos, to'lov tafsilotlarini yuborsangiz, darhol amalga oshiraman."
    ),
]


class UserbotManager:
    """Har bir ulangan foydalanuvchi uchun alohida Telethon user-client boshqaradi."""

    def __init__(self, bot_client: TelegramClient, bot_username: str | None = None):
        self.bot_client = bot_client
        self.bot_username = bot_username
        # asosiy akkaunt: user_db_id -> TelegramClient
        self.clients: dict[int, TelegramClient] = {}
        # qo'shimcha akkauntlar: extra_account_id -> TelegramClient
        self.extra_clients: dict[int, TelegramClient] = {}
        self._forward_times: dict[int, deque] = {}
        self._customer_dm_times: dict[int, deque] = {}
        # token -> {"user_db_id": int, "sender": Telethon entity} — tasdiqlash kutayotgan
        # "mijozga yozaymi?" so'rovlari
        self._pending_customer_greetings: dict[str, dict] = {}
        # token -> {"owner_tg_user_id", "owner_db_id", "sender_id", "sender_name", "chat_id"} —
        # buyurtma kartasidagi "⚙️ Amallar" tugmasi orqali botga o'tgan, hali amalga
        # oshirilmagan (bloklash) so'rovlar.
        self._pending_order_actions: dict[str, dict] = {}
        self.claims: dict[tuple[int, int], str] = {}
        # (user_db_id, chat_id) -> ketma-ket muvaffaqiyatsizliklar soni (o'lik guruhlarni aniqlash uchun)
        self._ad_failure_counts: dict[tuple[int, int], int] = {}
        # tg_user_id lar to'plami - hozir "Faqat ruxsat berilgan guruhlar" ro'yxatiga
        # ko'plab guruh havolasi/ID yuborayotgan, "Bekor qilish" tugmasini bosguncha
        # shu rejimda qoladi.
        self._bulk_allow_mode: set[int] = set()
        # user_db_id lar to'plami - hozir "Guruhlarga qo'shilish" fon vazifasi
        # ishlab turgan (qayta bosilganda ikki marta ishga tushmasligi uchun).
        self._joining_allowed_groups: set[int] = set()

    def enter_bulk_allow(self, tg_user_id: int) -> None:
        self._bulk_allow_mode.add(tg_user_id)

    def exit_bulk_allow(self, tg_user_id: int) -> None:
        self._bulk_allow_mode.discard(tg_user_id)

    def is_bulk_allow(self, tg_user_id: int) -> bool:
        return tg_user_id in self._bulk_allow_mode

    def is_joining_allowed_groups(self, user_db_id: int) -> bool:
        return user_db_id in self._joining_allowed_groups

    def _mark_joining_allowed_groups(self, user_db_id: int, active: bool) -> None:
        if active:
            self._joining_allowed_groups.add(user_db_id)
        else:
            self._joining_allowed_groups.discard(user_db_id)

    def _customer_dm_rate_limited(self, user_db_id: int) -> bool:
        now = time.monotonic()
        times = self._customer_dm_times.setdefault(user_db_id, deque())
        while times and now - times[0] > CUSTOMER_DM_RATE_LIMIT_WINDOW_SECONDS:
            times.popleft()
        if len(times) >= CUSTOMER_DM_RATE_LIMIT_COUNT:
            return True
        times.append(now)
        return False

    async def _maybe_send_customer_greeting(self, current, sender, matched_text: str = "") -> None:
        """Guruhda mijoz deb aniqlangan odamga shaxsiy DM orqali salomlashadi
        (agar foydalanuvchi shu funksiyani o'zi yoqqan bo'lsa). Soatlik limitdan
        (CUSTOMER_DM_RATE_LIMIT_COUNT) oshgan mijozlar uchun avtomatik yubormaydi —
        buning o'rniga xo'jayindan Ha/Yo'q tugmalari bilan so'raydi."""
        if not current.customer_greeting_enabled:
            return

        if not self.clients.get(current.id):
            return

        should_send = await asyncio.to_thread(db_utils.should_send_greeting, current.id, sender.id)
        if not should_send:
            return

        if self._customer_dm_rate_limited(current.id):
            await self._ask_customer_greeting_approval(current, sender, matched_text)
            return

        await self._send_customer_greeting(current, sender)

    def _pick_customer_greeting_client(self, user_db_id: int) -> TelegramClient | None:
        """Qo'shimcha akkaunt(lar) qo'shilgan bo'lsa, mijozga birinchi topilgan ulangan
        qo'shimcha akkauntdan yuboriladi (asosiy akkauntni "toza" saqlash uchun) —
        qo'shimcha akkaunt bo'lmasa, asosiy akkauntdan yuboriladi."""
        for acc in db_utils.list_extra_accounts_by_user_db_id(user_db_id):
            client = self.extra_clients.get(acc.id)
            if client and client.is_connected():
                return client
        return self.clients.get(user_db_id)

    async def _send_customer_greeting(self, current, sender) -> None:
        client = self._pick_customer_greeting_client(current.id)
        if not client:
            return
        text = current.customer_greeting_text or DEFAULT_CUSTOMER_GREETING_TEMPLATE.format(
            bot_username=self.bot_username or ""
        )
        try:
            await client.send_message(sender, text, link_preview=False)
            await asyncio.to_thread(db_utils.record_greeting_sent, current.id, sender.id)
        except RPCError:
            logger.warning(
                "Mijozga shaxsiy salomlashuv yuborilmadi: user=%s, sender=%s", current.tg_user_id, sender.id
            )

    async def _ask_customer_greeting_approval(self, current, sender, matched_text: str) -> None:
        if len(self._pending_customer_greetings) >= MAX_PENDING_CUSTOMER_GREETINGS:
            logger.warning(
                "Tasdiqlash navbati to'lgan, so'rov o'tkazib yuborildi: user=%s", current.tg_user_id
            )
            return

        token = uuid.uuid4().hex[:10]
        self._pending_customer_greetings[token] = {"user_db_id": current.id, "sender": sender}

        name = (
            " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]))
            or str(sender.id)
        )
        username = f" (@{sender.username})" if getattr(sender, "username", None) else ""
        preview = (matched_text[:200] + "…") if len(matched_text) > 200 else matched_text

        text = (
            f"🙋 Mijoz aniqlandi: {name}{username}\n\n"
            f"💬 Xabari: {preview}\n\n"
            "Soatlik limit (1-2 ta) to'lgani uchun avtomatik yuborilmadi.\n"
            "Unga shaxsiy salomlashuv xabarini yuboraymi?"
        )
        buttons = [
            [
                Button.inline("✅ Ha, yubor", f"cgreet_yes:{token}".encode()),
                Button.inline("❌ Yo'q", f"cgreet_no:{token}".encode()),
            ]
        ]
        try:
            await self.bot_client.send_message(current.tg_user_id, text, buttons=buttons)
        except RPCError:
            logger.warning("Tasdiqlash so'rovini yuborib bo'lmadi: user=%s", current.tg_user_id)
            self._pending_customer_greetings.pop(token, None)

    def peek_pending_action(self, token: str) -> dict | None:
        """Tokenga bog'langan kutilayotgan amal ma'lumotini o'chirmasdan qaytaradi
        (\"⚙️ Amallar\" menyusini ko'rsatishdan oldin, kim ekanini tekshirish uchun)."""
        return self._pending_order_actions.get(token)

    def pop_pending_action(self, token: str) -> dict | None:
        """Tokenga bog'langan kutilayotgan amalni o'chirib qaytaradi (amal
        bajarilganda - masalan bloklashda - bir marta ishlatiladi)."""
        return self._pending_order_actions.pop(token, None)

    async def confirm_customer_greeting(self, token: str, approved: bool) -> str:
        """Ha/Yo'q tugmasi bosilganda chaqiriladi. Qisqa holat matnini qaytaradi:
        'sent', 'declined', 'expired' yoki 'error'."""
        pending = self._pending_customer_greetings.pop(token, None)
        if not pending:
            return "expired"
        if not approved:
            return "declined"

        current = await asyncio.to_thread(db_utils.find_user_by_id, pending["user_db_id"])
        if not current:
            return "error"

        await self._send_customer_greeting(current, pending["sender"])
        return "sent"

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

        try:
            await client.get_dialogs()
        except Exception:
            logger.exception(
                "Dialoglarni oldindan yuklashda xatolik: tg_user_id=%s", user.tg_user_id
            )

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
        # Extra akkauntlarni ham to'xtatish
        for acc in db_utils.list_extra_accounts_by_user_db_id(user_db_id):
            await self.stop_extra_client(acc.id)

    async def start_extra_client(self, acc, tg_user_id: int, user_db_id: int) -> bool:
        """Qo'shimcha akkaunt uchun client ishga tushiradi."""
        if acc.id in self.extra_clients:
            return True
        try:
            session_str = decrypt_session(acc.session_string)
        except InvalidToken:
            logger.error("Extra akkaunt %s sessiyasi buzilgan", acc.id)
            db_utils.remove_extra_account(acc.id, tg_user_id)
            return False

        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        try:
            await client.connect()
        except RPCError:
            logger.exception("Extra akkaunt %s ga ulanib bo'lmadi", acc.id)
            return False

        if not await client.is_user_authorized():
            await client.disconnect()
            db_utils.remove_extra_account(acc.id, tg_user_id)
            await self.notify(tg_user_id, f"⚠️ Qo'shimcha akkaunt ({acc.phone}) sessiyasi yaroqsiz, o'chirildi.")
            return False

        try:
            await client.get_dialogs()
        except Exception:
            logger.exception("Dialoglarni oldindan yuklashda xatolik: extra_acc=%s", acc.id)

        acc_id = acc.id

        @client.on(events.NewMessage(incoming=True))
        async def handler(event, user_db_id=user_db_id, tg_user_id=tg_user_id):
            await self._handle_message(event, user_db_id, tg_user_id)

        self.extra_clients[acc_id] = client
        logger.info("Extra userbot ishga tushdi: phone=%s, user=%s", acc.phone, tg_user_id)

        try:
            await self.sync_extra_account_groups(client, user_db_id)
        except Exception:
            logger.exception("Guruhlarni sinxronlashda xatolik: extra_acc=%s", acc.id)

        return True

    async def sync_extra_account_groups(self, client: TelegramClient, user_db_id: int) -> int:
        """Qo'shimcha akkaunt a'zo bo'lgan barcha guruhlarni kuzatiladigan guruhlar
        ro'yxatiga (AllowedGroup) kiritadi va agar istisnoda bo'lsa chiqaradi."""
        added_count = 0
        try:
            async for dialog in client.iter_dialogs():
                if not dialog.is_group:
                    continue
                chat_id = dialog.id
                title = dialog.name
                username = getattr(dialog.entity, "username", None)
                await asyncio.to_thread(db_utils.unexclude_group, user_db_id, chat_id)
                added = await asyncio.to_thread(
                    db_utils.add_allowed_group, user_db_id, chat_id, username, title
                )
                if added:
                    added_count += 1
            if added_count > 0:
                logger.info(
                    "Extra akkauntdan %s ta yangi guruh kuzatuvga qo'shildi: user_db_id=%s",
                    added_count,
                    user_db_id,
                )
        except Exception:
            logger.exception("Extra akkaunt guruhlarini sinxronlashda xatolik: user_db_id=%s", user_db_id)
        return added_count

    async def stop_extra_client(self, acc_id: int) -> None:
        client = self.extra_clients.pop(acc_id, None)
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
        # Qo'shimcha akkauntlarni ham ishga tushirish
        for acc in db_utils.get_all_extra_accounts():
            user = db_utils.find_user_by_id(acc.user_id)
            if user and user.is_active:
                await self.start_extra_client(acc, user.tg_user_id, user.id)

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

    async def send_renewal_reminders(self) -> None:
        """Obunasi tez orada (RENEWAL_REMINDER_DAYS kun ichida) tugaydigan foydalanuvchilar
        uchun, ularning O'Z akkountidan adminga chiroyli, tabiiy so'rov xabari yuboradi —
        shunda admin kimga qachon murojaat qilish kerakligini tabiiy ravishda biladi."""
        users = await asyncio.to_thread(db_utils.get_users_needing_renewal_reminder, RENEWAL_REMINDER_DAYS)
        for user in users:
            client = self.clients.get(user.id)
            if not client:
                continue

            days_left = max(1, (user.subscription_expires_at - datetime.utcnow()).days + 1)
            text = random.choice(RENEWAL_REQUEST_TEMPLATES).format(days=days_left)

            try:
                await client.send_message(ADMIN_CONTACT_ID, text)
                await asyncio.to_thread(db_utils.mark_renewal_reminder_sent, user.id)
                logger.info("Obuna uzaytirish so'rovi yuborildi: user=%s", user.tg_user_id)
            except RPCError:
                logger.warning(
                    "Obuna uzaytirish so'rovini yuborib bo'lmadi: user=%s", user.tg_user_id
                )

    async def _send_ad_to_groups(self, user, settings, target_ids: set[int]) -> int:
        client = self.clients.get(user.id)
        if not client:
            return 0
        sent = 0
        for chat_id in target_ids:
            key = (user.id, chat_id)
            try:
                await client.send_message(chat_id, settings.text, link_preview=False)
                sent += 1
                self._ad_failure_counts.pop(key, None)
                await asyncio.to_thread(db_utils.log_ad_sent, user.id)
            except (RPCError, ValueError) as exc:
                logger.warning("Reklama yuborilmadi: user=%s, chat=%s", user.tg_user_id, chat_id)
                await self._register_ad_failure(user, chat_id, key, exc)
            except Exception as exc:
                logger.exception(
                    "Reklama yuborishda kutilmagan xatolik: user=%s, chat=%s", user.tg_user_id, chat_id
                )
                await self._register_ad_failure(user, chat_id, key, exc)
            await asyncio.sleep(AD_SEND_DELAY_SECONDS)
        if sent:
            await asyncio.to_thread(db_utils.update_ad_last_sent, user.id, datetime.utcnow())
        return sent

    async def _register_ad_failure(self, user, chat_id: int, key: tuple[int, int], exc: Exception) -> None:
        """Bir guruhga ketma-ket bir necha marta reklama yuborib bo'lmasa (masalan,
        akkaunt guruhni tark etgan yoki guruh o'chirilgan), uni ro'yxatdan avtomatik
        olib tashlaydi va foydalanuvchiga xabar beradi."""
        count = self._ad_failure_counts.get(key, 0) + 1
        self._ad_failure_counts[key] = count

        if count < DEAD_AD_GROUP_FAILURE_THRESHOLD:
            return

        self._ad_failure_counts.pop(key, None)
        removed = await asyncio.to_thread(db_utils.remove_ad_target_group, user.id, chat_id)
        if removed:
            logger.info(
                "O'lik reklama guruhi avtomatik o'chirildi: user=%s, chat=%s (%s marta muvaffaqiyatsiz)",
                user.tg_user_id,
                chat_id,
                count,
            )
            await self.notify(
                user.tg_user_id,
                f"⚠️ Reklama guruhi ({chat_id}) {count} marta ketma-ket yuborib bo'lmagani uchun "
                "reklama ro'yxatidan avtomatik olib tashlandi (ehtimol akkaunt guruhni tark etgan "
                "yoki guruh o'chirilgan). Kerak bo'lsa, guruhni qaytadan qo'shing.",
            )

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

    async def _handle_apk_protection(self, event, user_db_id: int, tg_user_id: int) -> bool:
        """APK fayl (shaxsiy chatda yoki guruhda) aniqlansa, imkon bo'lsa (guruhda admin
        huquqi bo'lsa) jim holda o'chiradi — xo'jayinga xabar yubormaydi. APK bo'lsa
        True qaytaradi (keyingi ishlov berish — salomlashuv/buyurtma tekshiruvi —
        to'xtatiladi)."""
        message = event.message
        if not _is_apk_message(message):
            return False

        current = await asyncio.to_thread(db_utils.find_user_by_id, user_db_id)
        if not current or not current.is_active:
            return True

        try:
            await message.client.delete_messages(event.chat_id, [message.id], revoke=True)
        except Exception:
            logger.warning(
                "APK xabarni o'chirib bo'lmadi (huquq yetarli emasdir): user=%s, chat=%s",
                current.tg_user_id,
                event.chat_id,
            )

        return True

    async def _handle_message(self, event, user_db_id: int, tg_user_id: int) -> None:
        if event.out:
            return

        if await self._handle_apk_protection(event, user_db_id, tg_user_id):
            return

        if event.is_private:
            await self._maybe_send_greeting(event, user_db_id, tg_user_id)
            return

        if not event.is_group:
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

    async def _maybe_send_greeting(self, event, user_db_id: int, tg_user_id: int) -> None:
        """Shaxsiy chatga kimdir yozganda (yangi odam yoki GREETING_COOLDOWN_DAYS'dan
        keyin qayta yozgan eski odam), avtomatik salomlashuv xabarini yuboradi."""
        sender = await event.get_sender()
        if not sender or getattr(sender, "bot", False):
            return

        current = await asyncio.to_thread(db_utils.find_user_by_id, user_db_id)
        if not current or not current.is_active or not current.greeting_enabled:
            return
        if not db_utils.is_subscription_active(current):
            return

        client = self.clients.get(user_db_id)
        if not client:
            return

        sender_id = event.sender_id
        should_send = await asyncio.to_thread(db_utils.should_send_greeting, user_db_id, sender_id)
        if not should_send:
            return

        text = current.greeting_text or DEFAULT_GREETING_TEMPLATE.format(
            bot_username=self.bot_username or ""
        )
        try:
            await client.send_message(event.chat_id, text, link_preview=False)
            await asyncio.to_thread(db_utils.record_greeting_sent, user_db_id, sender_id)
        except RPCError:
            logger.warning(
                "Salomlashuv xabarini yuborib bo'lmadi: user=%s, sender=%s", tg_user_id, sender_id
            )

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

    async def join_allowed_groups(self, user_db_id: int, delay_seconds: float = 25.0) -> dict:
        """\"Ruxsat etilgan guruhlar\" ro'yxatidagi, foydalanuvchining hech qaysi
        akkaunti a'zo bo'lmagan (ommaviy) guruhlariga akkauntlar o'rtasida teng
        taqsimlab (eng kam guruhga ega akkauntdan boshlab), sekin sur'atda qo'shiladi.
        Bitta akkaunt qo'sha olmasa (flood, ban va h.k.) - keyingi akkauntga o'tadi."""
        self._mark_joining_allowed_groups(user_db_id, True)
        try:
            return await self._join_allowed_groups_impl(user_db_id, delay_seconds)
        finally:
            self._mark_joining_allowed_groups(user_db_id, False)

    async def _join_allowed_groups_impl(self, user_db_id: int, delay_seconds: float) -> dict:
        clients: list[tuple[str, TelegramClient]] = []
        main = self.clients.get(user_db_id)
        if main and main.is_connected():
            clients.append(("asosiy", main))
        for acc in db_utils.list_extra_accounts_by_user_db_id(user_db_id):
            c = self.extra_clients.get(acc.id)
            if c and c.is_connected():
                clients.append((acc.phone, c))

        stats = {"joined": 0, "already": 0, "failed": 0, "skipped": 0}
        if not clients:
            return stats

        coverage: dict[int, set] = {}
        for i, (label, client) in enumerate(clients):
            ids = set()
            try:
                async for dialog in client.iter_dialogs():
                    if dialog.is_group or dialog.is_channel:
                        ids.add(dialog.id)
            except Exception:
                logger.exception("Dialoglarni o'qishda xatolik: %s", label)
            coverage[i] = ids

        allowed = await asyncio.to_thread(db_utils.list_allowed_groups, user_db_id)

        for group in allowed:
            if any(group.chat_id in coverage[i] for i in coverage):
                stats["already"] += 1
                continue

            if not group.username:
                stats["skipped"] += 1
                continue

            order = sorted(coverage.keys(), key=lambda i: len(coverage[i]))
            joined_ok = False
            for i in order:
                label, client = clients[i]
                try:
                    entity = await client.get_entity(group.username)
                    await client(JoinChannelRequest(entity))
                    coverage[i].add(group.chat_id)
                    stats["joined"] += 1
                    joined_ok = True
                    logger.info(
                        "Guruhga qo'shildi: %s -> %s", label, group.title or group.username
                    )
                    break
                except UserAlreadyParticipantError:
                    coverage[i].add(group.chat_id)
                    stats["already"] += 1
                    joined_ok = True
                    break
                except FloodWaitError as e:
                    logger.warning("Qo'shilishda flood-limit: %s, %ss", label, e.seconds)
                    continue
                except Exception as e:
                    logger.warning(
                        "Guruhga qo'shilmadi: %s -> %s: %s: %s",
                        label, group.title or group.username, type(e).__name__, e,
                    )
                    continue

            if not joined_ok:
                stats["failed"] += 1

            await asyncio.sleep(delay_seconds)

        return stats

    async def _get_client_for_chat(self, user_db_id: int, chat_id: int) -> TelegramClient | None:
        """Berilgan chat_id da a'zo bo'lgan birinchi clientni qaytaradi.
        Avval asosiy akkaunt, keyin extra akkauntlar tekshiriladi."""
        main = self.clients.get(user_db_id)
        if main:
            try:
                await main.get_entity(chat_id)
                return main
            except Exception:
                pass
        for acc in db_utils.list_extra_accounts_by_user_db_id(user_db_id):
            client = self.extra_clients.get(acc.id)
            if not client:
                continue
            try:
                await client.get_entity(chat_id)
                return client
            except Exception:
                continue
        return main  # fallback

    def _create_pending_action(self, owner_user_id: int, sender, name: str | None, chat_id: int) -> str:
        """Buyurtma kartasidagi \"⚙️ Amallar\" tugmasi bosilganda kerak bo'ladigan
        kontekstni (kimni yoki qaysi guruhni bloklash) tokenga bog'lab saqlaydi."""
        if len(self._pending_order_actions) >= MAX_PENDING_ORDER_ACTIONS:
            # Eng eski yozuvni tashlab, joy bo'shatamiz.
            oldest = next(iter(self._pending_order_actions), None)
            if oldest is not None:
                self._pending_order_actions.pop(oldest, None)
        token = uuid.uuid4().hex[:12]
        self._pending_order_actions[token] = {
            "owner_db_id": owner_user_id,
            "sender_id": sender.id,
            "sender_name": name or None,
            "chat_id": chat_id,
        }
        return token

    def _build_action_button(self, owner_user_id: int, sender, name: str | None, chat_id: int) -> list:
        """Buyurtma kartasiga qo'yiladigan yagona \"⚙️ Amallar\" tugmasini yaratadi -
        bosilganda botga (shaxsiy chatga) o'tkazadi, u yerda faqat egasi uchun
        amallar menyusi (bloklash va h.k.) ko'rsatiladi."""
        token = self._create_pending_action(owner_user_id, sender, name, chat_id)
        url = f"https://t.me/{self.bot_username}?start=act_{token}"
        return [Button.url("⚙️ Amallar", url, style="primary")]

    def _build_rich_order_message(
        self, order_card_id, name, phone, text, chat_title, chat_username, message, sender, owner_user_id
    ):
        """Ba'zi mijozlar uchun maxsus so'ralgan \"boy\" ko'rinishdagi buyurtma kartasi
        (yo'nalish, manba guruh va \"Zakazni yopish\" tugmasi bilan)."""
        route = extract_route(text)

        lines = ["🚕 <b>Yangi taxi so'rovi</b>", ""]
        lines.append(f"👤 {html.escape(name)}" if name else "👤 Noma'lum")
        _sender_username = getattr(sender, "username", None)
        _profile_url = f"https://t.me/{_sender_username}" if _sender_username else f"tg://user?id={sender.id}"
        _profile_label = html.escape(name) if name else f"ID {sender.id}"
        lines.append(
            f"🆔 ID {sender.id} · <a href=\"{_profile_url}\">{_profile_label}</a>"
        )
        if phone:
            lines.append(f"📞 {html.escape(phone)}")
        if route:
            lines.append(f"🛣 Yo'nalish: {html.escape(route[0])} → {html.escape(route[1])}")
        if chat_title:
            lines.append(f"📍 Manba: {html.escape(chat_title)}")
        lines.append("")
        lines.append(f"💬 {html.escape(text)}")
        lines.append("")
        lines.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        order_text = "\n".join(lines)

        rows = []
        if chat_username:
            rows.append(
                [Button.url("🔗 Manba xabari", f"https://t.me/{chat_username}/{message.id}", style="primary")]
            )
        rows.append(
            [Button.inline("✅ Zakazni yopish", f"close:{order_card_id}".encode(), style="success")]
        )
        rows.append(
            self._build_action_button(owner_user_id, sender, name, message.chat_id)
        )
        return order_text, rows

    async def _process_message(self, message, current, keywords, driver_keywords, excluded) -> bool:
        """`message` — NewMessage eventi yoki client.iter_messages() dan kelgan Message.
        Mos kelsa, buyurtmani buyurtma guruhga yuborib True qaytaradi."""
        if message.out or not message.is_group:
            return False

        if message.chat_id in excluded:
            return False

        if current.whitelist_only_groups:
            allowed = await asyncio.to_thread(db_utils.get_allowed_group_ids, current.id)
            if message.chat_id not in allowed:
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
                or has_emoji(text)
                or message.media
            ):
                return False
            matched = "aniqlanmagan (yo'lovchi deb qabul qilindi)"

        sender = await message.get_sender()
        if not sender or getattr(sender, "bot", False):
            return False

        blocked = await asyncio.to_thread(db_utils.is_sender_blocked, current.id, sender.id)
        if blocked:
            return False

        # Bitta odamdan bir vaqtning o'zida bir nechta zakaz kelib tushmasin.
        elapsed = await asyncio.to_thread(db_utils.seconds_since_last_order, current.id, sender.id)
        if elapsed is not None and elapsed < SENDER_COOLDOWN_SECONDS:
            logger.info(
                "Cooldown: user=%s sender=%s %.0fs oldin zakaz kelgan (kamida %ss kerak) - o'tkazib yuborildi",
                current.tg_user_id, sender.id, elapsed, SENDER_COOLDOWN_SECONDS,
            )
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

        extra_group_ids = await asyncio.to_thread(db_utils.get_extra_order_group_ids, current.id)
        destination_ids = [current.order_group_id, *extra_group_ids]

        order_card_id = None
        if current.rich_order_format:
            order_card_id = await asyncio.to_thread(
                db_utils.create_order_card, current.id, sender.id, name or None
            )
            order_text, buttons = self._build_rich_order_message(
                order_card_id, name, phone, text, chat_title, chat_username, message, sender, current.id
            )
        else:
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
                group_row.append(Button.url(f"📍 {chat_title or 'Guruh'}", f"https://t.me/{chat_username}", style="primary"))
            link_row = []
            if chat_username:
                link_row.append(Button.url("🔗 Xabarga o'tish", f"https://t.me/{chat_username}/{message.id}", style="primary"))
            _sender_uname = getattr(sender, "username", None)
            _profil_url = f"https://t.me/{_sender_uname}" if _sender_uname else f"tg://user?id={sender.id}"
            _profil_label = f"👤 {name}"[:40] if name else "👤 Profil"
            link_row.append(Button.url(_profil_label, _profil_url, style="primary"))
            buttons = [
                *([group_row] if group_row else []),
                link_row,
                self._build_action_button(current.id, sender, name, message.chat_id),
            ]

        sent_to_main = False
        for idx, dest_chat_id in enumerate(destination_ids):
            try:
                sent = await self.bot_client.send_message(
                    dest_chat_id, order_text, buttons=buttons, link_preview=False, parse_mode="html"
                )
                if idx == 0:
                    sent_to_main = True
                if order_card_id is not None:
                    await asyncio.to_thread(
                        db_utils.add_order_card_message, order_card_id, dest_chat_id, sent.id
                    )
            except (RPCError, ValueError):
                # ValueError - Telethon entity keshida topilmagan chat uchun (masalan bot
                # o'sha guruhdan chiqarib yuborilgan yoki hech qachon xabar ko'rmagan bo'lsa).
                # Buni ham RPCError kabi "shu manzilga yuborilmadi" deb hisoblab, davom etamiz -
                # aks holda butun buyurtma qayta ishlash to'xtab qoladi (mention, statistika va h.k.).
                if idx == 0:
                    logger.exception("Buyurtma guruhga yuborilmadi: user=%s", current.tg_user_id)
                    await self.notify(
                        current.tg_user_id,
                        "⚠️ Buyurtmani buyurtma guruhga yubora olmadim. Bot o'sha guruhda a'zoligini tekshiring.",
                    )
                else:
                    logger.warning(
                        "Qo'shimcha buyurtma guruhga yuborilmadi: user=%s, chat=%s",
                        current.tg_user_id,
                        dest_chat_id,
                    )

        if not sent_to_main:
            return False

        # Bot mijozni to'g'ridan-to'g'ri mention qila olmaydi (u bilan aloqada bo'lmagani
        # uchun access_hash yo'q). Akkaunt esa mijoz turgan guruhda a'zo bo'lgani uchun
        # haqiqiy bosiladigan mention yubora oladi.
        prefix = "👤 Mijoz: "
        mention_text = prefix + name
        try:
            mention_client = await self._get_client_for_chat(current.id, message.chat_id)
            if mention_client:
                input_user = utils.get_input_user(sender)
                offset = len(add_surrogate(prefix))
                length = len(add_surrogate(name))
                for dest_chat_id in destination_ids:
                    try:
                        await mention_client.send_message(
                            dest_chat_id,
                            mention_text,
                            formatting_entities=[
                                InputMessageEntityMentionName(offset=offset, length=length, user_id=input_user)
                            ],
                        )
                    except (RPCError, ValueError):
                        logger.warning(
                            "Mijoz mention xabari yuborilmadi: user=%s, chat=%s", current.tg_user_id, dest_chat_id
                        )
        except (RPCError, ValueError):
            logger.warning("Mijoz mention xabari yuborilmadi: user=%s", current.tg_user_id)

        await asyncio.to_thread(db_utils.log_order, current.id)
        await asyncio.to_thread(db_utils.mark_sender_order_sent, current.id, sender.id)

        await self._maybe_send_customer_greeting(current, sender, text)

        return True
