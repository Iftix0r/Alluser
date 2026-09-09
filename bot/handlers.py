import asyncio
import logging
import re

from telethon import TelegramClient, events
from telethon.errors import (
    AlreadyInConversationError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.custom import Button

import db_utils
from config import API_HASH, API_ID

logger = logging.getLogger(__name__)

ADMIN_CONTACT_USERNAME = "Iftix0r"
ADMIN_CONTACT_ID = 2114098498

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
    [Button.inline("✅ Ha, uzish", b"logout_yes", style="danger"), Button.inline("❌ Bekor qilish", b"logout_no")]
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
    unmatched_label = (
        "🧭 Aniqlanmagan: yo'lovchi ✅" if user.assume_passenger_if_unmatched else "🧭 Aniqlanmagan: yo'lovchi ❌"
    )
    return [
        [Button.inline("🔑 Kalit so'zlar", b"kw_menu"), Button.inline("🚖 Haydovchi so'zlari", b"dkw_menu")],
        [Button.inline("📦 Buyurtma guruhi", b"group_menu"), Button.inline("🗂 Kuzatiladigan guruhlar", b"groups_menu")],
        [Button.inline("📊 Holat", b"status"), Button.inline(active_label, b"toggle_active", style=active_style)],
        [Button.inline(unmatched_label, b"toggle_unmatched_passenger")],
        [Button.inline("🚫 Bloklanganlar", b"blocked_menu"), Button.inline("📢 Reklama", b"ad_menu")],
        [Button.inline("👥 Akkauntlar", b"accounts_menu"), Button.inline("❓ Yordam", b"help")],
        [Button.url("👨‍💼 Admin", f"https://t.me/{ADMIN_CONTACT_USERNAME}", style="primary")],
        [Button.inline("🔌 Akkauntni uzish", b"logout_confirm", style="danger")],
    ]


def keyword_submenu() -> list:
    return [
        [Button.inline("➕ Qo'shish", b"add_kw", style="success"), Button.inline("➖ O'chirish", b"del_kw", style="danger")],
        [Button.inline("📋 Ro'yxat", b"list_kw"), Button.inline("📤 Export", b"export_kw")],
        [Button.inline("« Bosh menyu", b"menu")],
    ]


def driver_keyword_submenu() -> list:
    return [
        [Button.inline("➕ Qo'shish", b"add_dkw", style="success"), Button.inline("➖ O'chirish", b"del_dkw", style="danger")],
        [Button.inline("📋 Ro'yxat", b"list_dkw"), Button.inline("📤 Export", b"export_dkw")],
        [Button.inline("« Bosh menyu", b"menu")],
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
        [Button.inline("🔗 ID orqali ulash", b"set_group"), Button.inline("🗑 Uzish", b"remove_group", style="danger")],
        [Button.url("➕ Qo'shimcha guruh", add_extra_url, style="success"), Button.inline("🗂 Qo'shimcha guruhlar", b"extra_groups_menu")],
        [Button.inline("« Bosh menyu", b"menu")],
    ]


def extra_order_groups_view(user_id: int) -> tuple[str, list]:
    groups = db_utils.list_extra_order_groups(user_id)
    if not groups:
        text = (
            "🗂 Qo'shimcha buyurtma guruhlari yo'q.\n\n"
            "Qo'shish uchun \"➕ Qo'shimcha guruh\" tugmasini bosib, botni kerakli guruhga qo'shing "
            f"(ko'pi bilan {db_utils.MAX_EXTRA_ORDER_GROUPS} ta)."
        )
        return text, [[Button.inline("« Orqaga", b"group_menu")]]
    lines = ["🗂 Qo'shimcha buyurtma guruhlari (buyurtmalar asosiy guruh bilan birga shu yerlarga ham yuboriladi):"]
    buttons = []
    for g in groups:
        label = g.title or str(g.chat_id)
        lines.append(f"- {label}")
        buttons.append([Button.inline(f"🗑 {label}"[:64], f"delordergroup:{g.id}".encode(), style="danger")])
    buttons.append([Button.inline("« Orqaga", b"group_menu")])
    return "\n".join(lines), buttons


def format_status(user) -> str:
    kws = db_utils.list_keywords(user.tg_user_id)
    dkws = db_utils.list_driver_keywords(user.tg_user_id)
    extra_groups = db_utils.list_extra_order_groups(user.id)
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
    async for dialog in client.iter_dialogs(limit=200):
        if not dialog.is_group:
            continue
        mark = "🔕" if dialog.id in excluded else "🔔"
        label = f"{mark} {dialog.name}"[:64]
        buttons.append([Button.inline(label, f"toggexc:{dialog.id}".encode())])
        if len(buttons) >= GROUPS_PAGE_LIMIT:
            break

    if not buttons:
        await respond("Siz a'zo bo'lgan guruhlar topilmadi.")
        return

    buttons.append([Button.inline("« Menyu", b"menu")])
    await respond(
        "🔔 = kuzatiladi, 🔕 = kuzatilmaydi. Holatni almashtirish uchun guruh nomini bosing:",
        buttons=buttons,
    )


def blocked_list_view(tg_user_id: int) -> tuple[str, list]:
    blocked = db_utils.list_blocked_senders(tg_user_id)
    buttons = [
        [Button.inline(f"❌ {b.sender_name or b.sender_id}"[:64], f"unblock:{b.sender_id}".encode(), style="success")]
        for b in blocked
    ]
    buttons.append([Button.inline("➕ ID/username orqali bloklash", b"block_add", style="danger")])
    buttons.append([Button.inline("« Bosh menyu", b"menu")])
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
        [Button.inline("✏️ Matnni sozlash", b"ad_set_text"), Button.inline("⏱ Intervalni sozlash", b"ad_set_interval")],
        [Button.inline("🗂 Guruhlarni tanlash", b"ad_groups_menu")],
        [Button.inline(active_label, b"ad_toggle_active", style=active_style), Button.inline("🚀 Hozir yuborish", b"ad_send_now", style="primary")],
        [Button.inline("« Bosh menyu", b"menu")],
    ]
    return text, buttons


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
        mark = "🟢" if dialog.id in selected else "⚪"
        label = f"{mark} {dialog.name}"[:64]
        buttons.append([Button.inline(label, f"toggad:{dialog.id}".encode())])
        if len(buttons) >= GROUPS_PAGE_LIMIT:
            break

    if not buttons:
        await respond("Siz a'zo bo'lgan guruhlar topilmadi.")
        return

    buttons.append([Button.inline("« Reklama menyusi", b"ad_menu")])
    await respond(
        "🟢 = reklama shu guruhga yuboriladi, ⚪ = yuborilmaydi. Holatni almashtirish uchun guruh nomini bosing:",
        buttons=buttons,
    )


def register_handlers(bot_client: TelegramClient, manager, bot_username: str) -> None:
    @bot_client.on(events.NewMessage(pattern="/start", func=lambda e: e.is_private))
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
        buttons.append([Button.inline("« Orqaga", b"kw_menu")])
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
            buttons.append([Button.inline("« Orqaga", b"kw_menu")])
            await event.edit("O'chirmoqchi bo'lgan kalit so'zni tanlang:", buttons=buttons)
        else:
            await event.edit("Kalit so'zlar qolmadi.", buttons=[[Button.inline("« Orqaga", b"kw_menu")]])

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
        buttons.append([Button.inline("« Orqaga", b"dkw_menu")])
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
            buttons.append([Button.inline("« Orqaga", b"dkw_menu")])
            await event.edit("O'chirmoqchi bo'lgan haydovchi so'zni tanlang:", buttons=buttons)
        else:
            await event.edit("Haydovchi so'zlari qolmadi.", buttons=[[Button.inline("« Orqaga", b"dkw_menu")]])

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

    elif data.startswith(b"toggexc:"):
        chat_id = int(data[len(b"toggexc:"):])
        now_excluded = db_utils.toggle_excluded_group(user.id, chat_id)
        await event.answer("🔕 Kuzatishdan chiqarildi" if now_excluded else "🔔 Kuzatishga qo'shildi")

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
    buttons.append([Button.inline("« Bosh menyu", b"menu")])
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
                phone = phone_msg.contact.phone_number.strip()
                if not phone.startswith("+"):
                    phone = "+" + phone
            else:
                phone = phone_msg.raw_text.strip()

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
                phone = phone_msg.contact.phone_number.strip()
                if not phone.startswith("+"):
                    phone = "+" + phone
            else:
                phone = phone_msg.raw_text.strip()

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
