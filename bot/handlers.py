import asyncio
import html
import logging
import re
import time

from telethon import TelegramClient, events
from telethon.errors import (
    AlreadyInConversationError,
    ChannelsTooMuchError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
)
from telethon.sessions import StringSession
from telethon.tl.custom import Button
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.utils import get_peer_id, parse_phone

import db_utils
from config import ADMIN_CONTACT_ID, ADMIN_CONTACT_USERNAME, API_HASH, API_ID

logger = logging.getLogger(__name__)

WELCOME = (
    "Salom! Bu bot orqali siz o'z Telegram akkauntingizni ulab, guruhlardagi "
    "xabarlarni kalit so'zlar bo'yicha kuzatib, mos xabarlarni buyurtmalar "
    "guruhingizga avtomatik yuborishingiz mumkin.\n\n"
    f"Ulangach {db_utils.TRIAL_DAYS} kunlik bepul sinov muddati beriladi, so'ngra "
    "xizmat pullik davom etadi.\n\n"
    "Boshlash uchun pastdagi \"📱 Telefon raqamni yuborish\" tugmasini bosing "
    "yoki raqamingizni xalqaro formatda qo'lda yozing (masalan: +998901234567):"
)

HELP = (
    "Buyruqlar:\n"
    "/start - akkauntni ulash\n"
    "/menu - tugmali bosh menyu\n"
    "/status - holatni ko'rish\n"
    "/addkeyword <so'z1>, <so'z2> - kalit so'z(lar) qo'shish\n"
    "/delkeyword <so'z1>, <so'z2> - kalit so'z(lar)ni o'chirish\n"
    "/keywords - kalit so'zlar ro'yxati\n"
    "/adddriverkeyword <so'z1>, <so'z2> - haydovchi so'z(lar) qo'shish\n"
    "/deldriverkeyword <so'z1>, <so'z2> - haydovchi so'z(lar)ni o'chirish\n"
    "/driverkeywords - haydovchi so'zlar ro'yxati\n"
    "/pause - kuzatishni to'xtatish\n"
    "/resume - kuzatishni davom ettirish\n"
    "/removegroup - buyurtma guruhni uzish\n"
    "/addordergroup - (guruh ichida) shu guruhni QO'SHIMCHA buyurtma guruhi qilib qo'shish\n"
    "/removeordergroup - (guruh ichida) shu guruhni qo'shimcha buyurtma guruhlaridan olib tashlash\n"
    "/groups - kuzatiladigan guruhlarni boshqarish\n"
    "/addgroup <havola yoki ID> - yangi guruhni kuzatuvga ulash\n"
    "/logout - akkauntni uzish\n\n"
    "Buyurtmalar guruhini ulash uchun bosh menyudagi \"📦 Buyurtma guruhi\" → "
    "\"➕ Guruhga qo'shish\" tugmasini bosing va ro'yxatdan guruhni tanlang — avtomatik ulanadi.\n\n"
    "Bir nechta buyurtma guruhi: asosiy guruhdan tashqari yana \"➕ Qo'shimcha guruh\" "
    f"orqali (ko'pi bilan {db_utils.MAX_EXTRA_ORDER_GROUPS} tagacha) qo'shishingiz mumkin — "
    "har bir buyurtma barcha ulangan guruhlarga bir vaqtda yuboriladi.\n\n"
    "Haydovchi so'zlari: agar xabarda shu so'zlardan biri bo'lsa, xabar buyurtma "
    "sifatida olinmaydi (masalan, haydovchilarning o'zaro yozishuvlarini chiqarib "
    "tashlash uchun).\n\n"
    "Ko'plab kalit so'z qo'shish/eksport: kalit so'z qo'shishda bir nechtasini vergul "
    "yoki alohida qatorlarga yozib, yoki katta ro'yxatni .txt fayl qilib yuborishingiz "
    "mumkin. \"📤 Export\" tugmasi orqali mavjud ro'yxatni nusxalab boshqa akkauntga ham "
    "qo'llash mumkin.\n\n"
    "Bloklash: buyurtma xabaridagi \"🚫 Bloklash\" tugmasini bossangiz, o'sha xabar "
    "buyurtma guruhidan o'chadi va o'sha mijozdan boshqa buyurtmalar kelmaydi. "
    "Bosh menyudagi \"🚫 Bloklanganlar\" bo'limida ID/username orqali oldindan ham "
    "bloklashingiz, yoki blokdan chiqarishingiz mumkin.\n\n"
    "Reklama: bosh menyudagi \"📢 Reklama\" bo'limida matn, yuborish intervali va "
    "qaysi guruhlarga yuborilishini sozlashingiz mumkin. Yoqilgach, belgilangan "
    "intervalda tanlangan guruhlarga avtomatik yuboriladi.\n\n"
    "Admin bilan bog'lanish: bosh menyudagi \"👨‍💼 Admin\" tugmasi orqali "
    f"(@{ADMIN_CONTACT_USERNAME}, ID: {ADMIN_CONTACT_ID})."
)

LOGOUT_CONFIRM_TEXT = (
    "Akkauntni uzsangiz, userbot kuzatishni to'xtatadi va qayta ulash uchun "
    "/start bosishingiz kerak bo'ladi. Davom etasizmi?"
)
LOGOUT_CONFIRM_BUTTONS = [
    [
        Button.inline("✅ Ha, uzish", b"logout_yes", style="danger"),
        Button.inline("❌ Bekor qilish", b"logout_no", style="primary"),
    ]
]

SET_GROUP_PROMPT_TEXT = (
    "📦 Buyurtmalar guruhining ID raqamini yuboring (masalan: -1001234567890).\n\n"
    "ID raqamni bilmasangiz, guruhdagi istalgan xabarni @userinfobot ga forward qiling "
    "— u sizga guruh ID sini ko'rsatadi."
)
SET_GROUP_INVALID_TEXT = "❌ Noto'g'ri ID. Faqat raqam yuboring (masalan: -1001234567890)."

ADD_KEYWORD_FAIL_TEXT = (
    f"Bu kalit so'z allaqachon mavjud, bo'sh yoki juda uzun "
    f"(ko'pi bilan {db_utils.MAX_KEYWORD_LENGTH} belgi)."
)
BUSY_TEXT = "Avvalgi amal hali tugallanmagan. Birozdan so'ng qayta urinib ko'ring."

_PUBLIC_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})/?$")
_PRIVATE_INVITE_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)")
_BARE_USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_]{5,32})$")


def _extract_public_username(text: str) -> str | None:
    """Guruh havolasidan (yoki @username dan) foydalanuvchi nomini ajratib oladi.
    Shaxsiy (invite-link) havola yoki noto'g'ri format bo'lsa - None qaytaradi."""
    text = text.strip()
    if _PRIVATE_INVITE_RE.match(text):
        return None
    m = _PUBLIC_LINK_RE.match(text)
    if m:
        return m.group(1)
    m = _BARE_USERNAME_RE.match(text)
    if m:
        return m.group(1)
    return None


_PRIVATE_MSG_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)(?:/\d+)?/?$")
_BARE_ID_RE = re.compile(r"^-?\d+$")


def _parse_group_reference(text: str) -> tuple[int | None, str | None]:
    """Guruh havolasi yoki ID sidan (chat_id, username) ni ajratib oladi.
    - t.me/c/<channel_id>/<msg_id> - shaxsiy xabar havolasi, chat_id to'g'ridan-to'g'ri
      hisoblanadi (tarmoqqa so'rov yubormasdan).
    - t.me/username yoki @username - username qaytariladi, chat_id keyin resolve qilinadi.
    - xom raqam (masalan -1001234567890 yoki 1234567890) - chat_id sifatida.
    Hech biriga mos kelmasa (None, None) qaytadi."""
    text = text.strip()

    m = _PRIVATE_MSG_LINK_RE.match(text)
    if m:
        channel_id = int(m.group(1))
        return -(1000000000000 + channel_id), None

    # Sof raqam (username emas) - _extract_public_username dan oldin tekshiriladi,
    # chunki uning bare-username regexi raqamli qatorlarga ham mos kelib qoladi.
    if _BARE_ID_RE.match(text):
        raw = int(text)
        chat_id = raw if raw < 0 else -(1000000000000 + raw)
        return chat_id, None

    username = _extract_public_username(text)
    if username:
        return None, username

    return None, None


_GROUP_LINK_FINDALL_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_+/]+")
_BARE_USERNAME_MENTION_RE = re.compile(r"(?<!\S)@([A-Za-z0-9_]{5,32})(?!\S)")


def _extract_group_refs(text: str) -> list[str]:
    """Erkin matn ichidan (masalan, boshqa gap-so'zlar bilan aralash yuborilgan
    ro'yxatdan) guruh havolalarini (t.me/...), @username larni va alohida
    qatordagi xom ID larni ajratib oladi - qolgan matnni e'tiborsiz qoldiradi."""
    refs: list[str] = []
    seen: set[str] = set()

    for m in _GROUP_LINK_FINDALL_RE.finditer(text):
        link = m.group(0).rstrip(").,;​")
        if link not in seen:
            seen.add(link)
            refs.append(link)

    for m in _BARE_USERNAME_MENTION_RE.finditer(text):
        ref = m.group(0)
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)

    for line in text.splitlines():
        line = line.strip()
        if line and _BARE_ID_RE.match(line) and line not in seen:
            seen.add(line)
            refs.append(line)

    return refs[:100]


GENERIC_ERROR_TEXT = "Xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring."
SUBSCRIPTION_EXPIRED_TEXT = (
    "⛔ Obunangiz muddati tugagan. Xizmatdan davom etish uchun admin bilan bog'lanib "
    "to'lovni amalga oshiring."
)


def parse_words(raw: str) -> list[str]:
    """Vergul yoki qator (yangi satr) bilan ajratilgan so'zlarni ajratib oladi —
    shu tufayli katta ro'yxatni bittada, har birini alohida qatorga yozib ham
    qo'shish mumkin (bulk import)."""
    words = [w.strip() for chunk in raw.replace("\r", "").split("\n") for w in chunk.split(",")]
    seen = set()
    result = []
    for w in words:
        if w and w.lower() not in seen:
            seen.add(w.lower())
            result.append(w)
    return result


async def extract_words_from_response(resp) -> list[str]:
    """Javobda matn fayl (.txt) bo'lsa uni yuklab olib o'qiydi, aks holda oddiy
    xabar matnidan so'zlarni ajratib oladi (bulk import uchun)."""
    if resp.document:
        try:
            data = await resp.download_media(bytes)
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            logger.warning("Yuklangan faylni o'qib bo'lmadi")
            text = resp.raw_text or ""
    else:
        text = resp.raw_text or ""
    return parse_words(text)


def summarize_add_results(results: dict[str, bool]) -> str:
    added = [w for w, ok in results.items() if ok]
    failed = [w for w, ok in results.items() if not ok]
    lines = []
    if added:
        lines.append("✅ Qo'shildi: " + ", ".join(added))
    if failed:
        lines.append("⚠️ Qo'shilmadi (mavjud/bo'sh/juda uzun): " + ", ".join(failed))
    return "\n".join(lines) if lines else ADD_KEYWORD_FAIL_TEXT


def summarize_remove_results(results: dict[str, bool]) -> str:
    removed = [w for w, ok in results.items() if ok]
    failed = [w for w, ok in results.items() if not ok]
    lines = []
    if removed:
        lines.append("✅ O'chirildi: " + ", ".join(removed))
    if failed:
        lines.append("⚠️ Topilmadi: " + ", ".join(failed))
    return "\n".join(lines) if lines else "Bunday kalit so'z topilmadi."


def main_menu(user) -> list:
    active_label = "⏸ Pauza qilish" if user.is_active else "▶️ Davom ettirish"
    active_style = "danger" if user.is_active else "success"
    unmatched_style = "success" if user.assume_passenger_if_unmatched else "danger"
    unmatched_label = (
        "🧭 Aniqlanmagan: yo'lovchi ✅" if user.assume_passenger_if_unmatched else "🧭 Aniqlanmagan: yo'lovchi ❌"
    )
    return [
        [
            Button.inline("🔑 Kalit so'zlar", b"kw_menu", style="primary"),
            Button.inline("🚖 Haydovchi so'zlari", b"dkw_menu", style="primary"),
        ],
        [
            Button.inline("📦 Buyurtma guruhi", b"group_menu", style="primary"),
            Button.inline("🗂 Kuzatiladigan guruhlar", b"groups_menu", style="primary"),
        ],
        [Button.inline("📊 Holat", b"status", style="primary"), Button.inline(active_label, b"toggle_active", style=active_style)],
        [Button.inline(unmatched_label, b"toggle_unmatched_passenger", style=unmatched_style)],
        [
            Button.inline("🚫 Bloklanganlar", b"blocked_menu", style="primary"),
            Button.inline("📢 Reklama", b"ad_menu", style="primary"),
        ],
        [
            Button.inline("👋 Salomlashuv xabari", b"greeting_menu", style="primary"),
        ],
        [
            Button.inline("👥 Akkauntlar", b"accounts_menu", style="primary"),
            Button.inline("👤 Adminlar", b"admins_menu", style="primary"),
        ],
        [Button.inline("🔒 Faqat ruxsat berilgan guruhlar", b"allowed_menu", style="primary")],
        [Button.inline("❓ Yordam", b"help", style="primary")],
        [Button.url("👨‍💼 Admin", f"https://t.me/{ADMIN_CONTACT_USERNAME}", style="primary")],
        [Button.inline("🔌 Akkauntni uzish", b"logout_confirm", style="danger")],
    ]


def keyword_submenu() -> list:
    return [
        [Button.inline("➕ Qo'shish", b"add_kw", style="success"), Button.inline("➖ O'chirish", b"del_kw", style="danger")],
        [
            Button.inline("📋 Ro'yxat", b"list_kw", style="primary"),
            Button.inline("📤 Export", b"export_kw", style="primary"),
        ],
        [Button.inline("« Bosh menyu", b"menu", style="primary")],
    ]


def driver_keyword_submenu() -> list:
    return [
        [Button.inline("➕ Qo'shish", b"add_dkw", style="success"), Button.inline("➖ O'chirish", b"del_dkw", style="danger")],
        [
            Button.inline("📋 Ro'yxat", b"list_dkw", style="primary"),
            Button.inline("📤 Export", b"export_dkw", style="primary"),
        ],
        [Button.inline("« Bosh menyu", b"menu", style="primary")],
    ]


def export_words_text(words: list[str], empty_label: str) -> str:
    if not words:
        return empty_label
    return (
        "📤 Nusxa oling va boshqa akkauntga import qilish uchun ishlating "
        "(vergul bilan ajratilgan, yoki .txt fayl qilib ham yuborishingiz mumkin):\n\n"
        + ", ".join(words)
    )


def order_group_submenu(tg_user_id: int, bot_username: str) -> list:
    add_url = f"https://t.me/{bot_username}?startgroup=setgroup_{tg_user_id}"
    add_extra_url = f"https://t.me/{bot_username}?startgroup=addordergroup_{tg_user_id}"
    return [
        [Button.url("➕ Guruhga qo'shish", add_url, style="success")],
        [
            Button.inline("🔗 ID orqali ulash", b"set_group", style="primary"),
            Button.inline("🗑 Uzish", b"remove_group", style="danger"),
        ],
        [
            Button.url("➕ Qo'shimcha guruh", add_extra_url, style="success"),
            Button.inline("🗂 Qo'shimcha guruhlar", b"extra_groups_menu", style="primary"),
        ],
        [Button.inline("« Bosh menyu", b"menu", style="primary")],
    ]


def extra_order_groups_view(user_id: int) -> tuple[str, list]:
    groups = db_utils.list_extra_order_groups(user_id)
    if not groups:
        text = (
            "🗂 Qo'shimcha buyurtma guruhlari yo'q.\n\n"
            "Qo'shish uchun \"➕ Qo'shimcha guruh\" tugmasini bosib, botni kerakli guruhga qo'shing "
            f"(ko'pi bilan {db_utils.MAX_EXTRA_ORDER_GROUPS} ta)."
        )
        return text, [[Button.inline("« Orqaga", b"group_menu", style="primary")]]
    lines = ["🗂 Qo'shimcha buyurtma guruhlari (buyurtmalar asosiy guruh bilan birga shu yerlarga ham yuboriladi):"]
    buttons = []
    for g in groups:
        label = g.title or str(g.chat_id)
        lines.append(f"- {label}")
        buttons.append([Button.inline(f"🗑 {label}"[:64], f"delordergroup:{g.id}".encode(), style="danger")])
    buttons.append([Button.inline("« Orqaga", b"group_menu", style="primary")])
    return "\n".join(lines), buttons


def format_status(user) -> str:
    kws = db_utils.list_keywords(user.tg_user_id)
    dkws = db_utils.list_driver_keywords(user.tg_user_id)
    extra_groups = db_utils.list_extra_order_groups(user.id)
    order_stats = db_utils.get_user_order_stats(user.id)
    ad_stats = db_utils.get_user_ad_stats(user.id)
    return "\n".join(
        [
            f"📱 Telefon: {user.phone or '-'}",
            f"📦 Buyurtma guruh: {user.order_group_id or 'ulanmagan'}",
            f"🗂 Qo'shimcha buyurtma guruhlari: {len(extra_groups)} ta",
            f"✅ Faol: {'ha' if user.is_active else 'yoq'}",
            f"🧭 Aniqlanmagan xabarlarni yo'lovchi deb qabul qilish: {'ha' if user.assume_passenger_if_unmatched else 'yoq'}",
            f"💳 Obuna: {db_utils.format_subscription_status(user)}",
            f"🔑 Kalit so'zlar ({len(kws)}): {', '.join(kws) if kws else '-'}",
            f"🚖 Haydovchi so'zlari ({len(dkws)}): {', '.join(dkws) if dkws else '-'}",
            "",
            f"📊 Buyurtmalar — bugun: {order_stats['today']}, "
            f"7 kunda: {order_stats['week']}, jami: {order_stats['total']}",
            f"📣 Reklama xabarlari — bugun: {ad_stats['today']}, "
            f"7 kunda: {ad_stats['week']}, jami: {ad_stats['total']}",
        ]
    )


GROUPS_PAGE_LIMIT = 50


async def send_groups_list(respond, manager, user) -> None:
    client = manager.clients.get(user.id)
    if not client:
        await respond("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
        return

    excluded = db_utils.get_excluded_group_ids(user.id)
    buttons = []
    seen_chat_ids = set()
    async for dialog in client.iter_dialogs(limit=200):
        if not dialog.is_group:
            continue
        seen_chat_ids.add(dialog.id)
        is_excluded = dialog.id in excluded
        mark = "🔕" if is_excluded else "🔔"
        label = f"{mark} {dialog.name}"[:64]
        style = "danger" if is_excluded else "success"
        buttons.append([Button.inline(label, f"toggexc:{dialog.id}".encode(), style=style)])
        if len(buttons) >= GROUPS_PAGE_LIMIT:
            break

    # Ruxsat berilgan (qo'lda qo'shilgan) guruhlar dialoglarda chiqmagan bo'lsa ham qo'shish
    allowed_groups = db_utils.list_allowed_groups(user.id)
    for g in allowed_groups:
        if g.chat_id not in seen_chat_ids and len(buttons) < GROUPS_PAGE_LIMIT:
            seen_chat_ids.add(g.chat_id)
            is_excluded = g.chat_id in excluded
            mark = "🔕" if is_excluded else "🔔"
            label = f"{mark} {g.title or g.username or g.chat_id}"[:64]
            style = "danger" if is_excluded else "success"
            buttons.append([Button.inline(label, f"toggexc:{g.chat_id}".encode(), style=style)])

    action_buttons = [
        [Button.inline("➕ Guruh qo'shish", b"add_monitored_group", style="success")],
        [Button.inline("« Menyu", b"menu", style="primary")],
    ]

    if not buttons:
        await respond(
            "🗂 Sizda hali kuzatiladigan guruhlar mavjud emas.\n\n"
            "Yangi guruhni havola yoki ID raqami orqali ulash uchun \"➕ Guruh qo'shish\" tugmasini bosing:",
            buttons=action_buttons,
        )
        return

    buttons.extend(action_buttons)
    await respond(
        "🔔 = kuzatiladi, 🔕 = kuzatilmaydi. Holatni almashtirish uchun guruh nomini bosing:\n\n"
        "➕ Yangi guruh ulash uchun \"➕ Guruh qo'shish\" tugmasini bosing:",
        buttons=buttons,
    )


def blocked_list_view(tg_user_id: int) -> tuple[str, list]:
    blocked = db_utils.list_blocked_senders(tg_user_id)
    buttons = [
        [Button.inline(f"❌ {b.sender_name or b.sender_id}"[:64], f"unblock:{b.sender_id}".encode(), style="success")]
        for b in blocked
    ]
    buttons.append([Button.inline("➕ ID/username orqali bloklash", b"block_add", style="danger")])
    buttons.append([Button.inline("« Bosh menyu", b"menu", style="primary")])
    text = (
        "🚫 Bloklangan foydalanuvchilar (blokdan chiqarish uchun bosing):"
        if blocked
        else "🚫 Bloklangan foydalanuvchilar yo'q."
    )
    return text, buttons


def ad_menu_view(user) -> tuple[str, list]:
    settings = db_utils.get_ad_settings(user.tg_user_id)
    target_count = len(db_utils.get_ad_target_group_ids(user.id))
    preview = (settings.text[:80] + "…") if settings.text and len(settings.text) > 80 else (settings.text or "belgilanmagan")
    active_label = "⏸ O'chirish" if settings.is_active else "▶️ Yoqish"
    active_style = "danger" if settings.is_active else "success"
    status_label = "yoqilgan" if settings.is_active else "o'chirilgan"
    last_sent_label = settings.last_sent_at.strftime("%Y-%m-%d %H:%M") if settings.last_sent_at else "-"
    text = "\n".join(
        [
            "📢 Reklama sozlamalari:",
            "",
            f"📝 Matn: {preview}",
            f"⏱ Interval: {settings.interval_minutes} daqiqa",
            f"🗂 Tanlangan guruhlar: {target_count} ta",
            f"▶️ Holat: {status_label}",
            f"🕓 Oxirgi yuborilgan: {last_sent_label}",
        ]
    )
    buttons = [
        [
            Button.inline("✏️ Matnni sozlash", b"ad_set_text", style="primary"),
            Button.inline("⏱ Intervalni sozlash", b"ad_set_interval", style="primary"),
        ],
        [Button.inline("🗂 Guruhlarni tanlash", b"ad_groups_menu", style="primary")],
        [Button.inline(active_label, b"ad_toggle_active", style=active_style), Button.inline("🚀 Hozir yuborish", b"ad_send_now", style="primary")],
        [Button.inline("« Bosh menyu", b"menu", style="primary")],
    ]
    return text, buttons


def greeting_menu_view(user, bot_username: str) -> tuple[str, list]:
    from userbot.manager import DEFAULT_CUSTOMER_GREETING_TEMPLATE, DEFAULT_GREETING_TEMPLATE

    def _preview(text: str) -> str:
        return (text[:200] + "…") if len(text) > 200 else text

    is_custom = bool(user.greeting_text)
    active_text = user.greeting_text or DEFAULT_GREETING_TEMPLATE.format(bot_username=bot_username)
    enabled_label = "⏸ O'chirish" if user.greeting_enabled else "▶️ Yoqish"
    enabled_style = "danger" if user.greeting_enabled else "success"
    status_label = "yoqilgan" if user.greeting_enabled else "o'chirilgan"

    is_ccustom = bool(user.customer_greeting_text)
    active_ctext = user.customer_greeting_text or DEFAULT_CUSTOMER_GREETING_TEMPLATE.format(
        bot_username=bot_username
    )
    cenabled_label = "⏸ O'chirish" if user.customer_greeting_enabled else "▶️ Yoqish"
    cenabled_style = "danger" if user.customer_greeting_enabled else "success"
    cstatus_label = "yoqilgan" if user.customer_greeting_enabled else "o'chirilgan (standart)"

    lines = [
        "👋 Salomlashuv xabarlari sozlamalari:",
        "",
        "1️⃣ *Sizga shaxsiy yozganlarga:*",
        "Sizga shaxsiy chatda yozgan yangi odamga (yoki 2 kundan keyin qayta "
        "yozgan eski tanishga) avtomatik shu xabar yuboriladi.",
        f"📝 Matn {'(sizniki)' if is_custom else '(standart)'}: {_preview(active_text)}",
        f"▶️ Holat: {status_label}",
        "",
        "2️⃣ *Guruhda mijoz deb aniqlangan odamga:*",
        "Guruh xabari kalit so'zga mos kelib, mijoz deb aniqlansa, o'sha odamga "
        "shaxsan (siz birinchi bo'lib) shu xabar yuboriladi. Soatiga faqat 1-2 ta "
        "avtomatik yuboriladi (spamdan himoya) — qolganlari uchun sizga \"Ha/Yo'q\" "
        "tugmali so'rov keladi, o'zingiz qaror qilasiz.",
        f"📝 Matn {'(sizniki)' if is_ccustom else '(standart)'}: {_preview(active_ctext)}",
        f"▶️ Holat: {cstatus_label}",
    ]

    buttons = [
        [Button.inline("✏️ (1) Matnni o'zgartirish", b"greeting_set_text", style="primary")],
    ]
    if is_custom:
        buttons.append([Button.inline("↩️ (1) Standartga qaytarish", b"greeting_reset_text", style="primary")])
    buttons.append([Button.inline(f"(1) {enabled_label}", b"greeting_toggle", style=enabled_style)])

    buttons.append([Button.inline("✏️ (2) Matnni o'zgartirish", b"cgreeting_set_text", style="primary")])
    if is_ccustom:
        buttons.append([Button.inline("↩️ (2) Standartga qaytarish", b"cgreeting_reset_text", style="primary")])
    buttons.append([Button.inline(f"(2) {cenabled_label}", b"cgreeting_toggle", style=cenabled_style)])

    buttons.append([Button.inline("« Bosh menyu", b"menu", style="primary")])
    return "\n".join(lines), buttons


async def send_ad_groups_list(respond, manager, user) -> None:
    client = manager.clients.get(user.id)
    if not client:
        await respond("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
        return

    selected = db_utils.get_ad_target_group_ids(user.id)
    buttons = []
    async for dialog in client.iter_dialogs(limit=200):
        if not dialog.is_group:
            continue
        is_selected = dialog.id in selected
        mark = "🟢" if is_selected else "⚪"
        label = f"{mark} {dialog.name}"[:64]
        style = "success" if is_selected else "primary"
        buttons.append([Button.inline(label, f"toggad:{dialog.id}".encode(), style=style)])
        if len(buttons) >= GROUPS_PAGE_LIMIT:
            break

    if not buttons:
        await respond("Siz a'zo bo'lgan guruhlar topilmadi.")
        return

    buttons.append([Button.inline("« Reklama menyusi", b"ad_menu", style="primary")])
    await respond(
        "🟢 = reklama shu guruhga yuboriladi, ⚪ = yuborilmaydi. Holatni almashtirish uchun guruh nomini bosing:",
        buttons=buttons,
    )


# Ba'zan tarmoq beqaror bo'lganda (Telethon qayta ulanib, o'tkazib yuborilgan
# yangilanishlarni tiklaganda — "Got difference" jarayoni) bitta xabar ikki marta
# yetib kelishi mumkin. Shu sababli har bir xabarni (chat, xabar ID) bo'yicha faqat
# bir marta qayta ishlaymiz — ikkinchi nusxa butunlay e'tiborsiz qoldiriladi.
_seen_messages: dict[tuple[int, int], float] = {}
DEDUP_WINDOW_SECONDS = 60
MAX_DEDUP_ENTRIES = 3000


def _is_duplicate_update(chat_id: int, message_id: int) -> bool:
    key = (chat_id, message_id)
    now = time.monotonic()

    if len(_seen_messages) > MAX_DEDUP_ENTRIES:
        cutoff = now - DEDUP_WINDOW_SECONDS
        for k, seen_at in list(_seen_messages.items()):
            if seen_at < cutoff:
                del _seen_messages[k]

    if key in _seen_messages:
        return True
    _seen_messages[key] = now
    return False


def _is_order_authorized(owner, clicker_tg_id: int) -> bool:
    """Buyurtma kartasidagi \"⚙️ Amallar\" menyusidan kim foydalana olishini tekshiradi:
    akkaunt egasi yoki u qo'shgan qo'shimcha adminlardan biri."""
    if owner.tg_user_id == clicker_tg_id:
        return True
    return db_utils.is_team_admin(owner.id, clicker_tg_id)


def register_handlers(bot_client: TelegramClient, manager, bot_username: str) -> None:
    @bot_client.on(events.NewMessage())
    async def dedup_guard(event):
        if _is_duplicate_update(event.chat_id, event.id):
            logger.warning(
                "Takroriy xabar o'tkazib yuborildi (chat=%s, msg=%s) — takroriy yetkazib "
                "berish tufayli qayta ishlov berilmadi.",
                event.chat_id,
                event.id,
            )
            raise events.StopPropagation

    @bot_client.on(events.NewMessage(pattern=r"^/start(?:@\w+)?\s+act_(\S+)$", func=lambda e: e.is_private))
    async def order_action_menu_handler(event):
        token = event.pattern_match.group(1)
        pending = manager.peek_pending_action(token)
        if not pending:
            await event.respond("⏱ Bu so'rov eskirgan yoki allaqachon ishlatilgan.")
            return

        owner = db_utils.find_user_by_id(pending["owner_db_id"])
        if not owner or not _is_order_authorized(owner, event.sender_id):
            await event.respond("❌ Kechirasiz, siz admin emassiz.")
            return

        sender_label = pending.get("sender_name") or str(pending["sender_id"])
        buttons = [
            [Button.inline("🚫 Foydalanuvchini bloklash", f"act_block:{token}".encode(), style="danger")],
            [Button.inline("🔕 Guruhni bloklash", f"act_blockgroup:{token}".encode(), style="danger")],
            [Button.inline("❌ Bekor qilish", f"act_cancel:{token}".encode())],
        ]
        await event.respond(
            f"⚙️ <b>Amallar</b>\n\n👤 Yuboruvchi: {sender_label}\n\nNima qilmoqchisiz?",
            buttons=buttons,
            parse_mode="html",
        )

    @bot_client.on(events.CallbackQuery(func=lambda e: e.is_private and e.data and e.data.startswith(b"act_")))
    async def order_action_callback_handler(event):
        action, _, token = event.data.decode().partition(":")
        pending = manager.peek_pending_action(token)
        if not pending:
            await event.answer("⏱ Bu so'rov eskirgan.", alert=True)
            return

        owner = db_utils.find_user_by_id(pending["owner_db_id"])
        if not owner or not _is_order_authorized(owner, event.sender_id):
            await event.answer("❌ Kechirasiz, siz admin emassiz.", alert=True)
            return

        manager.pop_pending_action(token)

        if action == "act_cancel":
            await event.answer("Bekor qilindi.")
            await event.edit("❌ Bekor qilindi.")
            return

        if action == "act_block":
            db_utils.block_sender(owner.tg_user_id, pending["sender_id"], pending["sender_name"])
            await event.answer("🚫 Foydalanuvchi bloklandi.")
            await event.edit("🚫 Foydalanuvchi bloklandi. Endi undan zakaz kelmaydi.")
            return

        if action == "act_blockgroup":
            added = db_utils.exclude_group(owner.id, pending["chat_id"])
            await event.answer("🔕 Guruh bloklandi." if added else "ℹ️ Bu guruh allaqachon bloklangan edi.")
            await event.edit(
                "🔕 Guruh bloklandi. Endi bu guruhdan zakaz kelmaydi."
                if added else "ℹ️ Bu guruh allaqachon bloklangan edi."
            )
            return

        await event.answer(GENERIC_ERROR_TEXT, alert=True)

    @bot_client.on(events.NewMessage(pattern=r"^/start(?:@\w+)?\s*$", func=lambda e: e.is_private))
    async def start_handler(event):
        tg_user_id = event.sender_id
        user = db_utils.get_or_create_user(tg_user_id)
        if user.session_string:
            await event.respond("Akkauntingiz allaqachon ulangan. Bosh menyu:", buttons=main_menu(user))
            return
        await run_login_flow(bot_client, manager, event.chat_id, tg_user_id)

    @bot_client.on(events.NewMessage(pattern="/menu", func=lambda e: e.is_private))
    async def menu_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        await event.respond("Bosh menyu:", buttons=main_menu(user))

    @bot_client.on(events.NewMessage(pattern="/help", func=lambda e: e.is_private))
    async def help_handler(event):
        await event.respond(HELP)

    @bot_client.on(events.NewMessage(pattern="/status", func=lambda e: e.is_private))
    async def status_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        await event.respond(format_status(user))

    @bot_client.on(events.NewMessage(pattern=r"/addkeyword(?: (.+))?", func=lambda e: e.is_private))
    async def addkeyword_handler(event):
        raw = event.pattern_match.group(1)
        if not raw:
            await event.respond("Foydalanish: /addkeyword taksi, karta, dostavka")
            return
        words = parse_words(raw)
        results = {w: db_utils.add_keyword(event.sender_id, w) for w in words}
        await event.respond(summarize_add_results(results))

    @bot_client.on(events.NewMessage(pattern=r"/delkeyword(?: (.+))?", func=lambda e: e.is_private))
    async def delkeyword_handler(event):
        raw = event.pattern_match.group(1)
        if not raw:
            await event.respond("Foydalanish: /delkeyword taksi, karta, dostavka")
            return
        words = parse_words(raw)
        results = {w: db_utils.remove_keyword(event.sender_id, w) for w in words}
        await event.respond(summarize_remove_results(results))

    @bot_client.on(events.NewMessage(pattern="/keywords", func=lambda e: e.is_private))
    async def keywords_handler(event):
        kws = db_utils.list_keywords(event.sender_id)
        if kws:
            await event.respond("Kalit so'zlar:\n" + "\n".join(f"- {w}" for w in kws))
        else:
            await event.respond("Kalit so'zlar qo'shilmagan.")

    @bot_client.on(events.NewMessage(pattern=r"/adddriverkeyword(?: (.+))?", func=lambda e: e.is_private))
    async def adddriverkeyword_handler(event):
        raw = event.pattern_match.group(1)
        if not raw:
            await event.respond("Foydalanish: /adddriverkeyword bo'shman, band")
            return
        words = parse_words(raw)
        results = {w: db_utils.add_driver_keyword(event.sender_id, w) for w in words}
        await event.respond(summarize_add_results(results))

    @bot_client.on(events.NewMessage(pattern=r"/deldriverkeyword(?: (.+))?", func=lambda e: e.is_private))
    async def deldriverkeyword_handler(event):
        raw = event.pattern_match.group(1)
        if not raw:
            await event.respond("Foydalanish: /deldriverkeyword bo'shman, band")
            return
        words = parse_words(raw)
        results = {w: db_utils.remove_driver_keyword(event.sender_id, w) for w in words}
        await event.respond(summarize_remove_results(results))

    @bot_client.on(events.NewMessage(pattern="/driverkeywords", func=lambda e: e.is_private))
    async def driverkeywords_handler(event):
        dkws = db_utils.list_driver_keywords(event.sender_id)
        if dkws:
            await event.respond("Haydovchi so'zlari:\n" + "\n".join(f"- {w}" for w in dkws))
        else:
            await event.respond("Haydovchi so'zlari qo'shilmagan.")

    @bot_client.on(events.NewMessage(pattern="/pause", func=lambda e: e.is_private))
    async def pause_handler(event):
        db_utils.toggle_active(event.sender_id, False)
        await event.respond("⏸ Kuzatish to'xtatildi.")

    @bot_client.on(events.NewMessage(pattern="/resume", func=lambda e: e.is_private))
    async def resume_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        if not db_utils.is_subscription_active(user):
            await event.respond(SUBSCRIPTION_EXPIRED_TEXT)
            return
        db_utils.toggle_active(event.sender_id, True)
        await manager.start_client_for_user(user)
        await event.respond("▶️ Kuzatish davom ettirildi.")

    @bot_client.on(events.NewMessage(pattern="/setgroup", func=lambda e: e.is_group))
    async def setgroup_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Avval botga shaxsiy chatda /start yuborib akkauntingizni ulang.")
            return
        ok = db_utils.set_order_group(event.sender_id, event.chat_id)
        if ok:
            await event.respond("✅ Bu guruh buyurtmalar guruhi sifatida belgilandi.")
        else:
            await event.respond("Xatolik: avval akkauntni ulang.")

    @bot_client.on(events.NewMessage(pattern="/setgroup", func=lambda e: e.is_private))
    async def setgroup_wrong_chat_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        await event.respond(
            "ℹ️ Buyurtmalar guruhini ulash uchun \"➕ Guruhga qo'shish\" tugmasini bosib "
            "kerakli guruhni tanlang — guruh avtomatik ulanadi.",
            buttons=order_group_submenu(event.sender_id, bot_username),
        )

    @bot_client.on(
        events.NewMessage(pattern=r"^/start(?:@\w+)?\s+setgroup_(\d+)$", func=lambda e: e.is_group)
    )
    async def start_group_deeplink_handler(event):
        tg_user_id = int(event.pattern_match.group(1))
        user = db_utils.get_user(tg_user_id)
        if not user or not user.session_string:
            await event.respond("Bu guruhni ulashga urinilgan akkaunt topilmadi yoki ulanmagan.")
            return
        ok = db_utils.set_order_group(tg_user_id, event.chat_id)
        await event.respond(
            "✅ Bu guruh buyurtmalar guruhi sifatida belgilandi."
            if ok
            else "Xatolik: avval akkauntni ulang."
        )

    @bot_client.on(events.NewMessage(pattern="/addordergroup", func=lambda e: e.is_group))
    async def addordergroup_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Avval botga shaxsiy chatda /start yuborib akkauntingizni ulang.")
            return
        chat = await event.get_chat()
        title = getattr(chat, "title", None)
        ok = db_utils.add_extra_order_group(user.id, event.chat_id, title)
        if ok:
            await event.respond("✅ Bu guruh qo'shimcha buyurtma guruhi sifatida qo'shildi.")
        else:
            await event.respond(
                "❌ Qo'shib bo'lmadi (allaqachon qo'shilgan yoki ko'pi bilan "
                f"{db_utils.MAX_EXTRA_ORDER_GROUPS} ta guruh qo'shish mumkin)."
            )

    @bot_client.on(events.NewMessage(pattern="/removeordergroup", func=lambda e: e.is_group))
    async def removeordergroup_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Avval botga shaxsiy chatda /start yuborib akkauntingizni ulang.")
            return
        match = next(
            (g for g in db_utils.list_extra_order_groups(user.id) if g.chat_id == event.chat_id), None
        )
        if not match:
            await event.respond("Bu guruh qo'shimcha buyurtma guruhi sifatida ulanmagan.")
            return
        db_utils.remove_extra_order_group(user.id, match.id)
        await event.respond("✅ Bu guruh qo'shimcha buyurtma guruhlar ro'yxatidan olib tashlandi.")

    @bot_client.on(
        events.NewMessage(pattern=r"^/start(?:@\w+)?\s+addordergroup_(\d+)$", func=lambda e: e.is_group)
    )
    async def add_order_group_deeplink_handler(event):
        tg_user_id = int(event.pattern_match.group(1))
        user = db_utils.get_user(tg_user_id)
        if not user or not user.session_string:
            await event.respond("Bu guruhni ulashga urinilgan akkaunt topilmadi yoki ulanmagan.")
            return
        chat = await event.get_chat()
        title = getattr(chat, "title", None)
        ok = db_utils.add_extra_order_group(user.id, event.chat_id, title)
        if ok:
            await event.respond("✅ Bu guruh qo'shimcha buyurtma guruhi sifatida qo'shildi.")
        else:
            await event.respond(
                "❌ Qo'shib bo'lmadi (allaqachon qo'shilgan yoki ko'pi bilan "
                f"{db_utils.MAX_EXTRA_ORDER_GROUPS} ta guruh qo'shish mumkin)."
            )

    @bot_client.on(events.CallbackQuery(func=lambda e: e.is_group and e.data == b"order_claim"))
    async def order_claim_handler(event):
        key = (event.chat_id, event.message_id)
        claimed_by = manager.claims.get(key)
        if claimed_by:
            await event.answer(f"Bu buyurtmani {claimed_by} allaqachon oldi.", alert=True)
            return

        clicker = await event.get_sender()
        name = " ".join(
            filter(None, [getattr(clicker, "first_name", None), getattr(clicker, "last_name", None)])
        ) or "Foydalanuvchi"
        manager.claims[key] = name

        message = await event.get_message()
        await event.edit(f"{message.raw_text}\n\n✅ Qabul qilindi: {name}", parse_mode=None)
        await event.answer("✅ Siz oldingiz!")

    @bot_client.on(events.CallbackQuery(func=lambda e: e.is_group and e.data and e.data.startswith(b"block:")))
    async def order_block_handler(event):
        try:
            _, sender_id_s, owner_id_s = event.data.decode().split(":")
            sender_id = int(sender_id_s)
            owner_user_id = int(owner_id_s)
        except ValueError:
            await event.answer(GENERIC_ERROR_TEXT, alert=True)
            return

        owner = db_utils.find_user_by_id(owner_user_id)
        if not owner:
            await event.answer("Xatolik: foydalanuvchi topilmadi.", alert=True)
            return

        message = await event.get_message()
        name_match = re.search(r"👤 Ism: (.+)", message.raw_text or "")
        sender_name = name_match.group(1).strip() if name_match else None

        db_utils.block_sender(owner.tg_user_id, sender_id, sender_name)
        await event.answer("🚫 Foydalanuvchi bloklandi, xabar o'chirilmoqda.")
        try:
            await bot_client.delete_messages(event.chat_id, [event.message_id])
        except Exception:
            logger.warning("Bloklangan buyurtma xabarini o'chirib bo'lmadi: chat=%s", event.chat_id)

    @bot_client.on(events.CallbackQuery(func=lambda e: e.is_group and e.data and e.data.startswith(b"blockgroup:")))
    async def order_blockgroup_handler(event):
        try:
            _, chat_id_s, owner_id_s = event.data.decode().split(":")
            chat_id = int(chat_id_s)
            owner_user_id = int(owner_id_s)
        except ValueError:
            await event.answer(GENERIC_ERROR_TEXT, alert=True)
            return

        owner = db_utils.find_user_by_id(owner_user_id)
        if not owner:
            await event.answer("Xatolik: foydalanuvchi topilmadi.", alert=True)
            return

        added = db_utils.exclude_group(owner.id, chat_id)
        await event.answer(
            "🔕 Guruh bloklandi, endi bu guruhdan zakaz kelmaydi."
            if added else "ℹ️ Bu guruh allaqachon bloklangan edi."
        )
        try:
            await bot_client.delete_messages(event.chat_id, [event.message_id])
        except Exception:
            logger.warning("Bloklangan guruh buyurtma xabarini o'chirib bo'lmadi: chat=%s", event.chat_id)

    @bot_client.on(events.CallbackQuery(func=lambda e: e.is_group and e.data and e.data.startswith(b"close:")))
    async def order_close_handler(event):
        try:
            order_card_id = int(event.data.decode().split(":", 1)[1])
        except ValueError:
            await event.answer(GENERIC_ERROR_TEXT, alert=True)
            return

        closer = await event.get_sender()
        closer_name = " ".join(
            filter(None, [getattr(closer, "first_name", None), getattr(closer, "last_name", None)])
        ) or "Foydalanuvchi"

        closed = await asyncio.to_thread(db_utils.close_order_card, order_card_id, closer_name)
        if not closed:
            await event.answer("Bu buyurtma allaqachon yopilgan.", alert=True)
            return

        await event.answer("✅ Zakaz yopildi!")

        pairs = await asyncio.to_thread(db_utils.get_order_card_messages, order_card_id)
        for chat_id, message_id in pairs:
            try:
                msg = await bot_client.get_messages(chat_id, ids=message_id)
                if not msg:
                    continue
                new_text = f"{msg.raw_text}\n\n✅ ZAKAZ YOPILDI\n👤 Yopdi: {closer_name}"
                await bot_client.edit_message(chat_id, message_id, new_text, buttons=None, parse_mode=None)
            except Exception:
                logger.warning(
                    "Zakaz kartasini tahrirlab bo'lmadi: order_card=%s, chat=%s", order_card_id, chat_id
                )

    @bot_client.on(events.NewMessage(pattern="/removegroup", func=lambda e: e.is_private))
    async def removegroup_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        ok = db_utils.clear_order_group(event.sender_id)
        await event.respond("✅ Buyurtma guruh uzildi." if ok else "Buyurtma guruh ulanmagan edi.")

    @bot_client.on(events.NewMessage(pattern="/groups", func=lambda e: e.is_private))
    async def groups_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        await send_groups_list(event.respond, manager, user)

    @bot_client.on(events.NewMessage(pattern=r"/addgroup(?: (.+))?", func=lambda e: e.is_private))
    async def addgroup_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan. /start bosing.")
            return
        client = manager.clients.get(user.id)
        if not client:
            if not user.is_active:
                await event.respond(
                    "⏸ Hisobingiz pauzada. Bosh menyudan \"▶️ Davom ettirish\" bosing."
                )
            else:
                await event.respond("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
            return

        raw_arg = (event.pattern_match.group(1) or "").strip()
        if raw_arg:
            status_msg = await event.respond("⏳ Guruh tekshirilmoqda va ulanmoqda...")
            result = await _connect_and_add_monitored_group(manager, user, raw_arg)
            await status_msg.edit(
                result,
                parse_mode="html",
                buttons=[
                    [Button.inline("🗂 Kuzatiladigan guruhlar", b"groups_menu", style="primary")],
                    [Button.inline("« Bosh menyu", b"menu", style="primary")],
                ],
            )
        else:
            await event.respond(
                "➕ <b>Kuzatiladigan guruh qo'shish</b>\n\n"
                "Foydalanish: <code>/addgroup &lt;havola yoki ID&gt;</code>\n\n"
                "Masalan:\n"
                "• <code>/addgroup https://t.me/guruh_nomi</code>\n"
                "• <code>/addgroup https://t.me/+havola</code>\n"
                "• <code>/addgroup -1001234567890</code>\n\n"
                "Yoki <b>\"🗂 Kuzatiladigan guruhlar\"</b> bo'limidagi <b>\"➕ Guruh qo'shish\"</b> tugmasidan foydalaning.",
                parse_mode="html",
            )

    @bot_client.on(events.NewMessage(func=lambda e: e.is_private and manager.is_bulk_allow(e.sender_id)))
    async def bulk_allow_message_handler(event):
        text = (event.raw_text or "").strip()
        if not text or text.startswith("/"):
            return  # komandalar shu rejimda ham odatdagidek ishlayveradi

        user = db_utils.get_user(event.sender_id)
        if not user:
            return
        client = manager.clients.get(user.id)
        if not client:
            if not user.is_active:
                await event.respond(
                    "⏸ Hisobingiz hozir pauzada — shuning uchun userbot ishlamayapti. "
                    "Avval bosh menyudan \"▶️ Davom ettirish\" tugmasini bosing, keyin qayta urinib ko'ring."
                )
            else:
                await event.respond("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
            raise events.StopPropagation

        refs = _extract_group_refs(text)
        if not refs:
            raise events.StopPropagation

        results = []
        for ref in refs:
            results.append(await _add_one_allowed_group(client, user, ref))
            await asyncio.sleep(1.0)  # ResolveUsername so'rovlarini flood qilmaslik uchun

        for i in range(0, len(results), 30):
            await event.respond("\n".join(results[i:i + 30]))
        raise events.StopPropagation

    @bot_client.on(events.CallbackQuery(func=lambda e: e.is_private and e.data == b"allow_bulk_done"))
    async def allow_bulk_done_handler(event):
        manager.exit_bulk_allow(event.sender_id)
        await event.answer("✅ Tugatildi.")
        user = db_utils.get_user(event.sender_id)
        if not user:
            await event.edit("✅ Tugatildi.")
            return
        text, buttons = await _allowed_menu_view(user)
        await event.edit(text, buttons=buttons, parse_mode="html")

    @bot_client.on(events.NewMessage(pattern="/logout", func=lambda e: e.is_private))
    async def logout_handler(event):
        user = db_utils.get_user(event.sender_id)
        if not user or not user.session_string:
            await event.respond("Akkaunt ulanmagan.")
            return
        await event.respond(LOGOUT_CONFIRM_TEXT, buttons=LOGOUT_CONFIRM_BUTTONS)

    @bot_client.on(events.CallbackQuery())
    async def callback_handler(event):
        if not event.is_private:
            return
        if event.data and event.data.startswith(b"admin_"):
            return  # bot/admin_handlers.py o'z alohida handlerida ishlov beradi

        tg_user_id = event.sender_id
        user = db_utils.get_user(tg_user_id)
        if not user or not user.session_string:
            await event.answer("Avval /start bosib akkauntingizni ulang.", alert=True)
            return

        data = event.data

        try:
            await _dispatch_callback(event, data, tg_user_id, user, bot_client, manager, bot_username)
        except Exception:
            logger.exception("Callback ishlov berishda xatolik: data=%s, user=%s", data, tg_user_id)
            try:
                await event.answer(GENERIC_ERROR_TEXT, alert=True)
            except Exception:
                await event.respond(GENERIC_ERROR_TEXT)


async def _dispatch_callback(event, data, tg_user_id, user, bot_client, manager, bot_username: str) -> None:
    if data == b"menu":
        user = db_utils.get_user(tg_user_id)
        await event.edit("Bosh menyu:", buttons=main_menu(user))

    elif data == b"kw_menu":
        await event.answer()
        await event.edit("🔑 Kalit so'zlar:", buttons=keyword_submenu())

    elif data == b"dkw_menu":
        await event.answer()
        await event.edit("🚖 Haydovchi so'zlari:", buttons=driver_keyword_submenu())

    elif data == b"group_menu":
        await event.answer()
        await event.edit(
            f"📦 Buyurtma guruh: {user.order_group_id or 'ulanmagan'}",
            buttons=order_group_submenu(tg_user_id, bot_username),
        )

    elif data == b"help":
        await event.answer()
        await event.respond(HELP)

    elif data == b"status":
        await event.answer()
        await event.respond(format_status(user))

    elif data == b"toggle_active":
        new_active = not user.is_active
        if new_active and not db_utils.is_subscription_active(user):
            await event.answer(SUBSCRIPTION_EXPIRED_TEXT, alert=True)
            return
        db_utils.toggle_active(tg_user_id, new_active)
        if new_active:
            await manager.start_client_for_user(user)
        user = db_utils.get_user(tg_user_id)
        await event.answer("Holat yangilandi.")
        await event.edit("Bosh menyu:", buttons=main_menu(user))

    elif data == b"toggle_unmatched_passenger":
        new_value = not user.assume_passenger_if_unmatched
        db_utils.toggle_assume_passenger(tg_user_id, new_value)
        user = db_utils.get_user(tg_user_id)
        await event.answer("Sozlama yangilandi.")
        await event.edit("Bosh menyu:", buttons=main_menu(user))

    elif data == b"list_kw":
        kws = db_utils.list_keywords(tg_user_id)
        await event.answer()
        text = "Kalit so'zlar:\n" + "\n".join(f"- {w}" for w in kws) if kws else "Kalit so'zlar qo'shilmagan."
        await event.respond(text)

    elif data == b"export_kw":
        kws = db_utils.list_keywords(tg_user_id)
        await event.answer()
        await event.respond(export_words_text(kws, "Kalit so'zlar qo'shilmagan."))

    elif data == b"add_kw":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "Qo'shmoqchi bo'lgan kalit so'z(lar)ni yuboring. Bir nechtasini vergul "
                    "yoki alohida qatorlarga yozib yuborishingiz mumkin (masalan: taksi, karta, "
                    "dostavka), yoki katta ro'yxatni .txt fayl qilib yuboring (bulk import):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                words = await extract_words_from_response(resp)
                if not words:
                    await conv.send_message(ADD_KEYWORD_FAIL_TEXT)
                    return
                results = {w: db_utils.add_keyword(tg_user_id, w) for w in words}
                await conv.send_message(summarize_add_results(results))
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"del_kw":
        kws = db_utils.list_keywords(tg_user_id)
        if not kws:
            await event.answer("Kalit so'zlar yo'q.", alert=True)
            return
        buttons = [[Button.inline(f"❌ {w}", f"delkw:{w}".encode(), style="danger")] for w in kws]
        buttons.append([Button.inline("✏️ Bir nechtasini yozib o'chirish", b"del_kw_bulk", style="danger")])
        buttons.append([Button.inline("« Orqaga", b"kw_menu", style="primary")])
        await event.answer()
        await event.edit(
            "O'chirmoqchi bo'lgan kalit so'zni tanlang, yoki bir nechtasini vergul bilan "
            "yozib yuborish uchun pastdagi tugmani bosing:",
            buttons=buttons,
        )

    elif data == b"del_kw_bulk":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "O'chirmoqchi bo'lgan kalit so'z(lar)ni yuboring. Bir nechtasini vergul "
                    "yoki alohida qatorlarga yozib, yoki .txt fayl qilib yuborishingiz mumkin "
                    "(masalan: taksi, karta):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                words = await extract_words_from_response(resp)
                if not words:
                    await conv.send_message("Bunday kalit so'z topilmadi.")
                    return
                results = {w: db_utils.remove_keyword(tg_user_id, w) for w in words}
                await conv.send_message(summarize_remove_results(results))
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data.startswith(b"delkw:"):
        word = data[len(b"delkw:"):].decode()
        db_utils.remove_keyword(tg_user_id, word)
        await event.answer(f"O'chirildi: {word}")
        kws = db_utils.list_keywords(tg_user_id)
        if kws:
            buttons = [[Button.inline(f"❌ {w}", f"delkw:{w}".encode(), style="danger")] for w in kws]
            buttons.append([Button.inline("✏️ Bir nechtasini yozib o'chirish", b"del_kw_bulk", style="danger")])
            buttons.append([Button.inline("« Orqaga", b"kw_menu", style="primary")])
            await event.edit("O'chirmoqchi bo'lgan kalit so'zni tanlang:", buttons=buttons)
        else:
            await event.edit("Kalit so'zlar qolmadi.", buttons=[[Button.inline("« Orqaga", b"kw_menu", style="primary")]])

    elif data == b"list_dkw":
        dkws = db_utils.list_driver_keywords(tg_user_id)
        await event.answer()
        text = (
            "Haydovchi so'zlari:\n" + "\n".join(f"- {w}" for w in dkws)
            if dkws
            else "Haydovchi so'zlari qo'shilmagan."
        )
        await event.respond(text)

    elif data == b"export_dkw":
        dkws = db_utils.list_driver_keywords(tg_user_id)
        await event.answer()
        await event.respond(export_words_text(dkws, "Haydovchi so'zlari qo'shilmagan."))

    elif data == b"add_dkw":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "Qo'shmoqchi bo'lgan haydovchi so'z(lar)ni yuboring. Bir nechtasini "
                    "vergul yoki alohida qatorlarga yozib, yoki .txt fayl qilib yuborishingiz "
                    "mumkin (masalan: bo'shman, band).\n\n"
                    "Bu so'zlardan biri xabarda uchrasa, o'sha xabar buyurtma sifatida olinmaydi."
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                words = await extract_words_from_response(resp)
                if not words:
                    await conv.send_message(ADD_KEYWORD_FAIL_TEXT)
                    return
                results = {w: db_utils.add_driver_keyword(tg_user_id, w) for w in words}
                await conv.send_message(summarize_add_results(results))
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"del_dkw":
        dkws = db_utils.list_driver_keywords(tg_user_id)
        if not dkws:
            await event.answer("Haydovchi so'zlari yo'q.", alert=True)
            return
        buttons = [[Button.inline(f"❌ {w}", f"deldkw:{w}".encode(), style="danger")] for w in dkws]
        buttons.append([Button.inline("✏️ Bir nechtasini yozib o'chirish", b"del_dkw_bulk", style="danger")])
        buttons.append([Button.inline("« Orqaga", b"dkw_menu", style="primary")])
        await event.answer()
        await event.edit(
            "O'chirmoqchi bo'lgan haydovchi so'zni tanlang, yoki bir nechtasini vergul "
            "bilan yozib yuborish uchun pastdagi tugmani bosing:",
            buttons=buttons,
        )

    elif data == b"del_dkw_bulk":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "O'chirmoqchi bo'lgan haydovchi so'z(lar)ni yuboring. Bir nechtasini "
                    "vergul yoki alohida qatorlarga yozib, yoki .txt fayl qilib yuborishingiz mumkin:"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                words = await extract_words_from_response(resp)
                if not words:
                    await conv.send_message("Bunday haydovchi so'zi topilmadi.")
                    return
                results = {w: db_utils.remove_driver_keyword(tg_user_id, w) for w in words}
                await conv.send_message(summarize_remove_results(results))
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data.startswith(b"deldkw:"):
        word = data[len(b"deldkw:"):].decode()
        db_utils.remove_driver_keyword(tg_user_id, word)
        await event.answer(f"O'chirildi: {word}")
        dkws = db_utils.list_driver_keywords(tg_user_id)
        if dkws:
            buttons = [[Button.inline(f"❌ {w}", f"deldkw:{w}".encode(), style="danger")] for w in dkws]
            buttons.append([Button.inline("✏️ Bir nechtasini yozib o'chirish", b"del_dkw_bulk", style="danger")])
            buttons.append([Button.inline("« Orqaga", b"dkw_menu", style="primary")])
            await event.edit("O'chirmoqchi bo'lgan haydovchi so'zni tanlang:", buttons=buttons)
        else:
            await event.edit("Haydovchi so'zlari qolmadi.", buttons=[[Button.inline("« Orqaga", b"dkw_menu", style="primary")]])

    elif data == b"set_group":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(SET_GROUP_PROMPT_TEXT)
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                try:
                    group_id = int(resp.raw_text.strip())
                except ValueError:
                    await conv.send_message(SET_GROUP_INVALID_TEXT)
                    return
                ok = db_utils.set_order_group(tg_user_id, group_id)
                await conv.send_message("✅ Buyurtmalar guruhi ulandi." if ok else "Xatolik: avval akkauntni ulang.")
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"extra_groups_menu":
        await event.answer()
        text, buttons = extra_order_groups_view(user.id)
        await event.edit(text, buttons=buttons)

    elif data.startswith(b"delordergroup:"):
        group_id = int(data[len(b"delordergroup:"):])
        db_utils.remove_extra_order_group(user.id, group_id)
        await event.answer("🗑 O'chirildi.")
        text, buttons = extra_order_groups_view(user.id)
        await event.edit(text, buttons=buttons)

    elif data == b"groups_menu":
        await event.answer()
        await send_groups_list(event.respond, manager, user)

    elif data == b"add_monitored_group":
        await event.answer()
        client = manager.clients.get(user.id)
        if not client:
            if not user.is_active:
                await event.respond(
                    "⏸ Hisobingiz hozir pauzada — shuning uchun userbot ishlamayapti. "
                    "Avval bosh menyudan \"▶️ Davom ettirish\" tugmasini bosing, keyin qayta urinib ko'ring."
                )
            else:
                await event.respond("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
            return

        try:
            async with bot_client.conversation(event.chat_id, timeout=180) as conv:
                await conv.send_message(
                    "➕ <b>Kuzatiladigan guruh qo'shish</b>\n\n"
                    "Guruh ID raqami yoki havolasini yuboring:\n"
                    "• Ommaviy havola: <code>https://t.me/guruh_nomi</code> yoki <code>@guruh_nomi</code>\n"
                    "• Yopiq guruh taklif havolasi: <code>https://t.me/+havola...</code>\n"
                    "• Guruh ID raqami: <code>-1001234567890</code>\n\n"
                    "ℹ️ <i>Bot guruhga avtomatik ulanadi va yangi buyurtmalarni qabul qilishni boshlaydi.</i>\n\n"
                    "Bekor qilish uchun /cancel deb yozing.",
                    parse_mode="html",
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("⏳ Vaqt tugadi.")
                    return

                raw_text = (resp.raw_text or "").strip()
                if not raw_text or raw_text.lower() == "/cancel":
                    await conv.send_message("❌ Bekor qilindi.")
                    return

                status_msg = await conv.send_message("⏳ Guruh tekshirilmoqda va ulanmoqda...")
                result_text = await _connect_and_add_monitored_group(manager, user, raw_text)
                await status_msg.edit(
                    result_text,
                    parse_mode="html",
                    buttons=[
                        [Button.inline("🗂 Kuzatiladigan guruhlar", b"groups_menu", style="primary")],
                        [Button.inline("« Bosh menyu", b"menu", style="primary")],
                    ],
                )
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data.startswith(b"toggexc:"):
        chat_id = int(data[len(b"toggexc:"):])
        now_excluded = db_utils.toggle_excluded_group(user.id, chat_id)
        await event.answer("🔕 Kuzatishdan chiqarildi" if now_excluded else "🔔 Kuzatishga qo'shildi")
        try:
            msg = await event.get_message()
            if msg and msg.buttons:
                new_buttons = []
                for row in msg.buttons:
                    new_row = []
                    for btn in row:
                        if btn.data == data:
                            clean_text = btn.text.lstrip("🔔🔕 ")
                            new_mark = "🔕" if now_excluded else "🔔"
                            new_style = "danger" if now_excluded else "success"
                            new_row.append(Button.inline(f"{new_mark} {clean_text}"[:64], data, style=new_style))
                        else:
                            new_row.append(btn)
                    new_buttons.append(new_row)
                await event.edit(buttons=new_buttons)
        except Exception:
            pass

    elif data == b"remove_group":
        ok = db_utils.clear_order_group(tg_user_id)
        await event.answer("✅ Guruh uzildi." if ok else "Guruh ulanmagan edi.")
        user = db_utils.get_user(tg_user_id)
        await event.edit(
            f"📦 Buyurtma guruh: {user.order_group_id or 'ulanmagan'}",
            buttons=order_group_submenu(tg_user_id, bot_username),
        )

    elif data == b"blocked_menu":
        await event.answer()
        text, buttons = blocked_list_view(tg_user_id)
        await event.edit(text, buttons=buttons)

    elif data.startswith(b"unblock:"):
        sender_id = int(data[len(b"unblock:"):])
        ok = db_utils.unblock_sender(tg_user_id, sender_id)
        await event.answer("✅ Blokdan chiqarildi." if ok else "Topilmadi.")
        text, buttons = blocked_list_view(tg_user_id)
        await event.edit(text, buttons=buttons)

    elif data == b"block_add":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "Bloklamoqchi bo'lgan foydalanuvchining Telegram ID raqami yoki @username'ini "
                    "yuboring (u hali buyurtma yubormagan bo'lsa ham, oldindan bloklab qo'yishingiz mumkin):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                raw = resp.raw_text.strip()
                client = manager.clients.get(user.id)
                if not client:
                    await conv.send_message("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
                    return
                target = int(raw) if raw.lstrip("-").isdigit() else raw.lstrip("@")
                try:
                    entity = await client.get_entity(target)
                except Exception:
                    await conv.send_message(
                        "❌ Foydalanuvchi topilmadi. ID yoki @username to'g'ri ekanini tekshiring."
                    )
                    return
                name = " ".join(
                    filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)])
                ) or raw
                ok = db_utils.block_sender(tg_user_id, entity.id, name)
                await conv.send_message(f"✅ Bloklandi: {name}" if ok else "⚠️ Bu foydalanuvchi allaqachon bloklangan.")
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"ad_menu":
        await event.answer()
        text, buttons = ad_menu_view(user)
        await event.edit(text, buttons=buttons)

    elif data == b"ad_set_text":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=180) as conv:
                await conv.send_message(
                    f"Reklama matnini yuboring (ko'pi bilan {db_utils.MAX_AD_TEXT_LENGTH} belgi):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                ok = db_utils.set_ad_text(tg_user_id, resp.raw_text or "")
                if ok:
                    await conv.send_message("✅ Reklama matni saqlandi.")
                else:
                    await conv.send_message(
                        f"❌ Matn bo'sh yoki juda uzun (ko'pi bilan {db_utils.MAX_AD_TEXT_LENGTH} belgi)."
                    )
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"ad_set_interval":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "Reklama necha daqiqada bir marta yuborilsin? Raqam kiriting "
                    f"(kamida {db_utils.MIN_AD_INTERVAL_MINUTES} daqiqa, masalan: 60):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                try:
                    minutes = int(resp.raw_text.strip())
                except ValueError:
                    await conv.send_message("❌ Noto'g'ri qiymat. Faqat butun son yuboring.")
                    return
                ok = db_utils.set_ad_interval(tg_user_id, minutes)
                if ok:
                    await conv.send_message(f"✅ Interval {minutes} daqiqaga sozlandi.")
                else:
                    await conv.send_message(
                        f"❌ Interval kamida {db_utils.MIN_AD_INTERVAL_MINUTES} daqiqa bo'lishi kerak."
                    )
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"ad_groups_menu":
        await event.answer()
        await send_ad_groups_list(event.respond, manager, user)

    elif data.startswith(b"toggad:"):
        chat_id = int(data[len(b"toggad:"):])
        now_selected = db_utils.toggle_ad_target_group(user.id, chat_id)
        await event.answer("🟢 Ro'yxatga qo'shildi" if now_selected else "⚪ Ro'yxatdan olib tashlandi")

    elif data == b"ad_toggle_active":
        settings = db_utils.get_ad_settings(tg_user_id)
        new_value = not settings.is_active
        ok = db_utils.toggle_ad_active(tg_user_id, new_value)
        if not ok and new_value:
            await event.answer(
                "❌ Avval reklama matnini va kamida bitta guruhni belgilang.", alert=True
            )
            return
        await event.answer("✅ Yoqildi." if new_value else "⏸ O'chirildi.")
        text, buttons = ad_menu_view(user)
        await event.edit(text, buttons=buttons)

    elif data == b"ad_send_now":
        await event.answer("Yuborilmoqda...")
        sent = await manager.send_ad_now(user.id)
        if sent is None:
            await event.respond("❌ Avval reklama matnini va kamida bitta guruhni belgilang.")
        else:
            await event.respond(f"✅ {sent} ta guruhga yuborildi.")

    elif data == b"greeting_menu":
        await event.answer()
        text, buttons = greeting_menu_view(user, bot_username)
        await event.edit(text, buttons=buttons)

    elif data == b"greeting_set_text":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=180) as conv:
                await conv.send_message(
                    "Yangi salomlashuv xabari matnini yuboring "
                    f"(ko'pi bilan {db_utils.MAX_GREETING_TEXT_LENGTH} belgi):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                ok = db_utils.set_greeting_text(tg_user_id, resp.raw_text or "")
                if ok:
                    await conv.send_message("✅ Salomlashuv xabari saqlandi.")
                else:
                    await conv.send_message(
                        f"❌ Matn bo'sh yoki juda uzun (ko'pi bilan "
                        f"{db_utils.MAX_GREETING_TEXT_LENGTH} belgi)."
                    )
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"greeting_reset_text":
        db_utils.clear_greeting_text(tg_user_id)
        user = db_utils.get_user(tg_user_id)
        await event.answer("Standart matnga qaytarildi.")
        text, buttons = greeting_menu_view(user, bot_username)
        await event.edit(text, buttons=buttons)

    elif data == b"greeting_toggle":
        db_utils.toggle_greeting_enabled(tg_user_id)
        user = db_utils.get_user(tg_user_id)
        await event.answer()
        text, buttons = greeting_menu_view(user, bot_username)
        await event.edit(text, buttons=buttons)

    elif data == b"cgreeting_set_text":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=180) as conv:
                await conv.send_message(
                    "Guruhda mijoz deb aniqlangan odamga yuboriladigan shaxsiy salomlashuv "
                    f"matnini yuboring (ko'pi bilan {db_utils.MAX_GREETING_TEXT_LENGTH} belgi):"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                ok = db_utils.set_customer_greeting_text(tg_user_id, resp.raw_text or "")
                if ok:
                    await conv.send_message("✅ Mijozga salomlashuv matni saqlandi.")
                else:
                    await conv.send_message(
                        f"❌ Matn bo'sh yoki juda uzun (ko'pi bilan "
                        f"{db_utils.MAX_GREETING_TEXT_LENGTH} belgi)."
                    )
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data == b"cgreeting_reset_text":
        db_utils.clear_customer_greeting_text(tg_user_id)
        user = db_utils.get_user(tg_user_id)
        await event.answer("Standart matnga qaytarildi.")
        text, buttons = greeting_menu_view(user, bot_username)
        await event.edit(text, buttons=buttons)

    elif data == b"cgreeting_toggle":
        now_enabled = db_utils.toggle_customer_greeting_enabled(tg_user_id)
        user = db_utils.get_user(tg_user_id)
        if now_enabled:
            await event.answer(
                "Yoqildi! Diqqat: bu guruhda topilgan odamlarga birinchi bo'lib siz yozasiz — "
                "ehtiyotkorlik bilan ishlating.",
                alert=True,
            )
        else:
            await event.answer("O'chirildi.")
        text, buttons = greeting_menu_view(user, bot_username)
        await event.edit(text, buttons=buttons)

    elif data.startswith(b"cgreet_yes:") or data.startswith(b"cgreet_no:"):
        token = data.split(b":", 1)[1].decode()
        approved = data.startswith(b"cgreet_yes:")
        await event.answer()
        status = await manager.confirm_customer_greeting(token, approved)
        if status == "sent":
            await event.edit("✅ Salomlashuv xabari yuborildi.")
        elif status == "declined":
            await event.edit("❌ Bekor qilindi, xabar yuborilmadi.")
        elif status == "expired":
            await event.edit("⏱ Bu so'rov eskirgan yoki allaqachon hal qilingan.")
        else:
            await event.edit("❌ Xatolik yuz berdi.")

    elif data == b"logout_confirm":
        await event.answer()
        await event.respond(LOGOUT_CONFIRM_TEXT, buttons=LOGOUT_CONFIRM_BUTTONS)

    elif data == b"logout_yes":
        await manager.stop_client_for_user(user.id)
        db_utils.clear_session(tg_user_id)
        await event.answer("Akkaunt uzildi.")
        await event.edit("🔌 Akkaunt uzildi. Qayta ulash uchun /start bosing.")

    elif data == b"logout_no":
        await event.answer("Bekor qilindi.")
        await event.edit("Bosh menyu:", buttons=main_menu(user))

    elif data == b"accounts_menu":
        await event.answer()
        text, buttons = await _accounts_menu_view(tg_user_id)
        await event.edit(text, buttons=buttons)

    elif data == b"add_account":
        await event.answer()
        await run_extra_account_login(bot_client, manager, event.chat_id, tg_user_id)

    elif data.startswith(b"delacc:"):
        acc_id = int(data[len(b"delacc:"):])
        accs = db_utils.list_extra_accounts(tg_user_id)
        acc = next((a for a in accs if a.id == acc_id), None)
        if acc:
            await manager.stop_extra_client(acc_id)
            db_utils.remove_extra_account(acc_id, tg_user_id)
            await event.answer("O'chirildi.")
        else:
            await event.answer("Topilmadi.", alert=True)
        text, buttons = await _accounts_menu_view(tg_user_id)
        await event.edit(text, buttons=buttons)

    elif data == b"admins_menu":
        await event.answer()
        text, buttons = await _admins_menu_view(user.id)
        await event.edit(text, buttons=buttons)

    elif data == b"add_team_admin":
        await event.answer()
        try:
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message(
                    "Admin qilmoqchi bo'lgan odamning Telegram ID raqamini yuboring, "
                    "yoki undan kelgan istalgan xabarni shu yerga forward qiling:"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return

                admin_id = None
                admin_name = None
                if resp.forward and resp.forward.sender_id:
                    admin_id = resp.forward.sender_id
                    try:
                        fwd_sender = await resp.forward.get_sender()
                        admin_name = " ".join(
                            filter(
                                None,
                                [getattr(fwd_sender, "first_name", None), getattr(fwd_sender, "last_name", None)],
                            )
                        ) or None
                    except Exception:
                        pass
                elif resp.raw_text and resp.raw_text.strip().lstrip("-").isdigit():
                    admin_id = int(resp.raw_text.strip())
                else:
                    await conv.send_message("❌ Tushunmadim. ID raqam yuboring yoki xabarni forward qiling.")
                    return

                if admin_id == tg_user_id:
                    await conv.send_message("ℹ️ Siz allaqachon egasi sifatida to'liq huquqqa egasiz.")
                    return

                added = db_utils.add_team_admin(user.id, admin_id, admin_name)
                label = admin_name or str(admin_id)
                if added:
                    await conv.send_message(f"✅ {label} (ID: {admin_id}) admin qilib qo'shildi.")
                else:
                    await conv.send_message("ℹ️ Bu odam allaqachon admin edi.")
        except AlreadyInConversationError:
            await event.respond(BUSY_TEXT)

    elif data.startswith(b"delteamadmin:"):
        admin_id = int(data[len(b"delteamadmin:"):])
        removed = db_utils.remove_team_admin(user.id, admin_id)
        await event.answer("O'chirildi." if removed else "Topilmadi.", alert=not removed)
        text, buttons = await _admins_menu_view(user.id)
        await event.edit(text, buttons=buttons)

    elif data == b"allowed_menu":
        await event.answer()
        text, buttons = await _allowed_menu_view(user)
        await event.edit(text, buttons=buttons, parse_mode="html")

    elif data == b"toggle_whitelist":
        new_value = not user.whitelist_only_groups
        db_utils.toggle_whitelist_only_groups(tg_user_id, new_value)
        user = db_utils.get_user(tg_user_id)
        await event.answer("🔒 Yoqildi." if new_value else "🔓 O'chirildi.")
        text, buttons = await _allowed_menu_view(user)
        await event.edit(text, buttons=buttons, parse_mode="html")

    elif data == b"add_allowed_group":
        await event.answer()
        if not manager.clients.get(user.id):
            if not user.is_active:
                await event.respond(
                    "⏸ Hisobingiz hozir pauzada — shuning uchun userbot ishlamayapti. "
                    "Avval bosh menyudan \"▶️ Davom ettirish\" tugmasini bosing, keyin qayta urinib ko'ring."
                )
            else:
                await event.respond("Userbot hali ishga tushmagan. Birozdan so'ng qayta urinib ko'ring.")
            return
        manager.enter_bulk_allow(tg_user_id)
        await event.respond(
            "🔒 Ruxsat bermoqchi bo'lgan guruh(lar)ni yuboring — havola (https://t.me/guruh_nomi), "
            "shaxsiy xabar havolasi (t.me/c/...) yoki guruh ID raqami bo'lishi mumkin.\n\n"
            "Bir nechtasini bitta xabarda yoki ketma-ket alohida xabarlarda yuborishingiz mumkin. "
            "Tugatgach pastdagi tugmani bosing.",
            buttons=[[Button.inline("✅ Tugatdim / Bekor qilish", b"allow_bulk_done", style="danger")]],
        )

    elif data.startswith(b"delallow:"):
        chat_id_s, _, page_s = data[len(b"delallow:"):].decode().partition(":")
        chat_id = int(chat_id_s)
        page = int(page_s) if page_s else 0
        removed = db_utils.remove_allowed_group(user.id, chat_id)
        await event.answer("O'chirildi." if removed else "Topilmadi.", alert=not removed)
        text, buttons = await _allowed_menu_view(user, page)
        await event.edit(text, buttons=buttons, parse_mode="html")

    elif data.startswith(b"allowed_page:"):
        page = int(data[len(b"allowed_page:"):])
        await event.answer()
        text, buttons = await _allowed_menu_view(user, page)
        await event.edit(text, buttons=buttons, parse_mode="html")

    elif data == b"join_allowed_groups":
        if manager.is_joining_allowed_groups(user.id):
            await event.answer("⏳ Jarayon allaqachon ishlamoqda, kuting.", alert=True)
            return
        await event.answer("🔗 Boshlandi — sekin, xavfsiz sur'atda (har guruh uchun ~25s). Tugagach xabar beraman.")
        asyncio.create_task(_run_join_allowed_groups(manager, user))


async def _run_join_allowed_groups(manager, user) -> None:
    """Fon vazifasi: guruhlarga qo'shilishni ishga tushiradi va tugagach
    foydalanuvchiga shaxsiy xabarda natijani yuboradi."""
    try:
        stats = await manager.join_allowed_groups(user.id, delay_seconds=25.0)
    except Exception:
        logger.exception("Guruhlarga qo'shilish jarayonida xatolik: user=%s", user.tg_user_id)
        await manager.notify(user.tg_user_id, "❌ Guruhlarga qo'shilishda kutilmagan xatolik yuz berdi.")
        return

    text = (
        "🔗 <b>Guruhlarga qo'shilish yakunlandi</b>\n\n"
        f"✅ Yangi qo'shildi: {stats['joined']}\n"
        f"ℹ️ Allaqachon a'zo edi: {stats['already']}\n"
        f"⚠️ Qo'shib bo'lmadi: {stats['failed']}\n"
        f"⏭ O'tkazib yuborildi (shaxsiy/ID li): {stats['skipped']}"
    )
    try:
        await manager.bot_client.send_message(user.tg_user_id, text, parse_mode="html")
    except Exception:
        logger.exception("Natija xabarini yuborib bo'lmadi: user=%s", user.tg_user_id)


async def _admins_menu_view(user_id: int) -> tuple[str, list]:
    admins = db_utils.list_team_admins(user_id)
    lines = ["👤 Qo'shimcha adminlar (buyurtma kartasidagi \"⚙️ Amallar\" menyusidan foydalana oladi):"]
    buttons = []
    for a in admins:
        label = a.admin_name or str(a.admin_tg_id)
        lines.append(f"👤 {label} (ID: {a.admin_tg_id})")
        buttons.append([Button.inline(f"🗑 {label} ni o'chirish", f"delteamadmin:{a.admin_tg_id}".encode(), style="danger")])
    if not admins:
        lines.append("Hozircha qo'shimcha admin yo'q.")
    buttons.append([Button.inline("➕ Admin qo'shish", b"add_team_admin", style="success")])
    buttons.append([Button.inline("« Bosh menyu", b"menu", style="primary")])
    return "\n".join(lines), buttons


ALLOWED_GROUPS_PAGE_SIZE = 10


async def _allowed_menu_view(user, page: int = 0) -> tuple[str, list]:
    allowed = db_utils.list_allowed_groups(user.id)
    total = len(allowed)
    total_pages = max(1, (total + ALLOWED_GROUPS_PAGE_SIZE - 1) // ALLOWED_GROUPS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * ALLOWED_GROUPS_PAGE_SIZE
    page_items = allowed[start:start + ALLOWED_GROUPS_PAGE_SIZE]

    mode_label = "✅ Yoqilgan" if user.whitelist_only_groups else "❌ O'chirilgan"
    lines = [
        "🔒 <b>Faqat ruxsat berilgan guruhlar</b>",
        "",
        f"Holati: {mode_label}",
        f"Jami: {total} ta guruh (sahifa {page + 1}/{total_pages})",
        "",
        "Yoqilgan bo'lsa - hisobingiz a'zo bo'lgan qancha guruh bo'lishidan qat'iy nazar, "
        "buyurtmalar FAQAT shu ro'yxatdagi guruhlardan qidiriladi, qolganlari "
        "e'tiborsiz qoldiriladi.",
    ]
    buttons = [
        [Button.inline(
            f"{'🔓 Oʻchirish' if user.whitelist_only_groups else '🔒 Yoqish'}",
            b"toggle_whitelist", style="danger" if user.whitelist_only_groups else "success",
        )]
    ]
    for a in page_items:
        label = a.title or a.username or str(a.chat_id)
        lines.append(f"✅ {label}")
        buttons.append(
            [Button.inline(f"🗑 {label}"[:40], f"delallow:{a.chat_id}:{page}".encode(), style="danger")]
        )
    if not allowed:
        lines.append("Hozircha ro'yxat bo'sh.")

    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀ Oldingi", f"allowed_page:{page - 1}".encode(), style="primary"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("Keyingi ▶", f"allowed_page:{page + 1}".encode(), style="primary"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([Button.inline("➕ Guruh qo'shish", b"add_allowed_group", style="success")])
    buttons.append([Button.inline("🔗 Guruhlarga qo'shilish (avtomatik)", b"join_allowed_groups", style="primary")])
    buttons.append([Button.inline("« Bosh menyu", b"menu", style="primary")])
    return "\n".join(lines), buttons


async def _add_one_allowed_group(client, user, link: str) -> str:
    """Bitta guruh havolasi/IDsini tekshirib, \"ruxsat berilganlar\" ro'yxatiga qo'shadi.
    Havola, shaxsiy xabar havolasi (t.me/c/...) yoki xom ID bo'lishi mumkin - akkaunt
    allaqachon a'zo bo'lgan guruhlar uchun ishlatiladi."""
    chat_id, username = _parse_group_reference(link)
    if chat_id is None and username is None:
        return f"❌ {link} — tushunmadim. Havola, t.me/c/... yoki ID yuboring."

    title = None
    if chat_id is None:
        try:
            entity = await client.get_entity(username)
        except FloodWaitError as e:
            return (
                f"⏳ {link} — Telegram vaqtincha cheklov qo'ygan (juda ko'p so'rov), "
                f"{e.seconds}s dan keyin qayta urinib ko'ring."
            )
        except Exception as e:
            logger.warning("Guruhni topib bo'lmadi: %s — %s: %s", link, type(e).__name__, e)
            return f"❌ {link} — guruh/kanal topilmadi."
        chat_id = get_peer_id(entity)
        title = getattr(entity, "title", None)
    else:
        try:
            entity = await client.get_entity(chat_id)
            title = getattr(entity, "title", None)
        except Exception:
            pass  # Sarlavhasiz ham qo'shib bo'ladi - ID orqali baribir ishlaydi.

    title = title or username or str(chat_id)
    added = await asyncio.to_thread(db_utils.add_allowed_group, user.id, chat_id, username, title)
    if added:
        return f"✅ {title} — ruxsat berilgan guruhlar ro'yxatiga qo'shildi."
    return f"ℹ️ {title} — allaqachon ro'yxatda bor edi."


async def _accounts_menu_view(tg_user_id: int) -> tuple[str, list]:
    accs = db_utils.list_extra_accounts(tg_user_id)
    lines = ["👥 Qo'shimcha akkauntlar:"]
    buttons = []
    for acc in accs:
        lines.append(f"📱 {acc.phone}")
        buttons.append([Button.inline(f"🗑 {acc.phone} ni o'chirish", f"delacc:{acc.id}".encode(), style="danger")])
    if not accs:
        lines.append("Hozircha qo'shimcha akkaunt yo'q.")
    buttons.append([Button.inline("➕ Akkaunt qo'shish", b"add_account", style="success")])
    buttons.append([Button.inline("« Bosh menyu", b"menu", style="primary")])
    return "\n".join(lines), buttons


async def run_login_flow(bot_client: TelegramClient, manager, chat_id: int, tg_user_id: int) -> None:
    try:
        async with bot_client.conversation(chat_id, timeout=300) as conv:
            await conv.send_message(
                WELCOME,
                buttons=[[Button.request_phone("📱 Telefon raqamni yuborish", style="primary")]],
            )
            phone_msg = await conv.get_response()
            if phone_msg.contact:
                phone = (phone_msg.contact.phone_number or "").strip()
                if phone and not phone.startswith("+"):
                    phone = "+" + phone
            else:
                phone = (phone_msg.raw_text or "").strip()

            if not phone or not parse_phone(phone):
                await conv.send_message(
                    "Telefon raqam formati noto'g'ri. Iltimos, qaytadan /start bosing va "
                    "raqamni faqat raqamlardan iborat xalqaro formatda yuboring "
                    "(masalan: +998901234567).",
                    buttons=Button.clear(),
                )
                return

            user_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await user_client.connect()

            try:
                sent = await user_client.send_code_request(phone)
            except PhoneNumberInvalidError:
                await conv.send_message("Telefon raqam noto'g'ri. Qaytadan /start bosing.", buttons=Button.clear())
                await user_client.disconnect()
                return

            await conv.send_message(
                "Telegram sizga kod yubordi.\n\n"
                "⚠️ Kodni to'g'ridan-to'g'ri (masalan 12345) yubormang — Telegram buni "
                "xavfsizlik maqsadida avtomatik aniqlab, kodni bekor qilib qo'yadi. "
                "Buning o'rniga raqamlar orasiga vergul qo'yib yuboring, masalan: 1,2,3,4,5",
                buttons=Button.clear(),
            )
            code_msg = await conv.get_response()
            code = re.sub(r"\D", "", code_msg.raw_text)

            try:
                await user_client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
            except SessionPasswordNeededError:
                await conv.send_message("Ikki bosqichli tekshiruv (2FA) parolingizni kiriting:")
                pwd_msg = await conv.get_response()
                await user_client.sign_in(password=pwd_msg.raw_text.strip())
            except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                await conv.send_message("Kod noto'g'ri yoki eskirgan. Qaytadan /start bosing.")
                await user_client.disconnect()
                return

            session_string = user_client.session.save()
            await user_client.disconnect()

            db_utils.save_session(tg_user_id, phone, session_string)
            db_utils.start_trial(tg_user_id)
            user = db_utils.get_user(tg_user_id)
            await manager.start_client_for_user(user)

            await conv.send_message(
                "✅ Akkaunt ulandi!\n\n"
                f"🎁 Sizga {db_utils.TRIAL_DAYS} kunlik bepul sinov muddati berildi.\n\n"
                "Endi \"🔗 Buyurtma guruhini ulash\" tugmasini bosib buyurtmalar guruhi "
                "ID raqamini yuboring.\n\n"
                "Kalit so'zlarni tugmalar orqali ham boshqarishingiz mumkin:",
                buttons=main_menu(user),
            )
    except asyncio.TimeoutError:
        await bot_client.send_message(chat_id, "Vaqt tugadi. Qaytadan /start bosing.")
    except AlreadyInConversationError:
        await bot_client.send_message(chat_id, BUSY_TEXT)
    except Exception:
        logger.exception("Login jarayonida xatolik: %s", tg_user_id)
        await bot_client.send_message(chat_id, "Xatolik yuz berdi. Qaytadan /start bosing.")


async def run_extra_account_login(bot_client: TelegramClient, manager, chat_id: int, tg_user_id: int) -> None:
    try:
        async with bot_client.conversation(chat_id, timeout=300) as conv:
            await conv.send_message(
                "Qo'shmoqchi bo'lgan akkauntning telefon raqamini yuboring (masalan: +998901234567):",
                buttons=[[Button.request_phone("📱 Telefon raqamni yuborish", style="primary")]],
            )
            phone_msg = await conv.get_response()
            if phone_msg.contact:
                phone = (phone_msg.contact.phone_number or "").strip()
                if phone and not phone.startswith("+"):
                    phone = "+" + phone
            else:
                phone = (phone_msg.raw_text or "").strip()

            if not phone or not parse_phone(phone):
                await conv.send_message(
                    "Telefon raqam formati noto'g'ri. Faqat raqamlardan iborat xalqaro "
                    "formatda yuboring (masalan: +998901234567). Qaytadan urinib ko'ring.",
                    buttons=Button.clear(),
                )
                return

            user_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await user_client.connect()

            try:
                sent = await user_client.send_code_request(phone)
            except PhoneNumberInvalidError:
                await conv.send_message("Telefon raqam noto'g'ri.", buttons=Button.clear())
                await user_client.disconnect()
                return

            await conv.send_message(
                "Telegram sizga kod yubordi. Raqamlar orasiga vergul qo'yib yuboring (masalan: 1,2,3,4,5):",
                buttons=Button.clear(),
            )
            code_msg = await conv.get_response()
            code = re.sub(r"\D", "", code_msg.raw_text)

            try:
                await user_client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
            except SessionPasswordNeededError:
                await conv.send_message("2FA parolingizni kiriting:")
                pwd_msg = await conv.get_response()
                await user_client.sign_in(password=pwd_msg.raw_text.strip())
            except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                await conv.send_message("Kod noto'g'ri yoki eskirgan. Qaytadan urinib ko'ring.")
                await user_client.disconnect()
                return

            session_string = user_client.session.save()
            await user_client.disconnect()

            acc = db_utils.add_extra_account(tg_user_id, phone, session_string)
            user = db_utils.get_user(tg_user_id)
            await manager.start_extra_client(acc, tg_user_id, user.id)

            await conv.send_message(f"✅ Qo'shimcha akkaunt ({phone}) ulandi!")
    except asyncio.TimeoutError:
        await bot_client.send_message(chat_id, "Vaqt tugadi.")
    except AlreadyInConversationError:
        await bot_client.send_message(chat_id, BUSY_TEXT)
    except Exception:
        logger.exception("Extra akkaunt login xatolik: %s", tg_user_id)
        await bot_client.send_message(chat_id, "Xatolik yuz berdi.")
