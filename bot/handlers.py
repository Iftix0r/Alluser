import asyncio
import logging

from telethon import TelegramClient, events
from telethon.errors import (
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

WELCOME = (
    "Salom! Bu bot orqali siz o'z Telegram akkauntingizni ulab, guruhlardagi "
    "xabarlarni kalit so'zlar bo'yicha kuzatib, mos xabarlarni buyurtmalar "
    "guruhingizga avtomatik yuborishingiz mumkin.\n\n"
    "Boshlash uchun telefon raqamingizni xalqaro formatda yuboring "
    "(masalan: +998901234567):"
)

HELP = (
    "Buyruqlar:\n"
    "/start - akkauntni ulash\n"
    "/menu - tugmali bosh menyu\n"
    "/status - holatni ko'rish\n"
    "/addkeyword <so'z> - kalit so'z qo'shish\n"
    "/delkeyword <so'z> - kalit so'zni o'chirish\n"
    "/keywords - kalit so'zlar ro'yxati\n"
    "/pause - kuzatishni to'xtatish\n"
    "/resume - kuzatishni davom ettirish\n"
    "/removegroup - buyurtma guruhni uzish\n"
    "/groups - kuzatiladigan guruhlarni boshqarish\n"
    "/logout - akkauntni uzish\n\n"
    "Buyurtmalar guruhini ulash uchun botni o'sha guruhga qo'shing va guruh "
    "ichida /setgroup buyrug'ini yuboring (faqat akkaunt ulangan foydalanuvchi "
    "bajara oladi)."
)

LOGOUT_CONFIRM_TEXT = (
    "Akkauntni uzsangiz, userbot kuzatishni to'xtatadi va qayta ulash uchun "
    "/start bosishingiz kerak bo'ladi. Davom etasizmi?"
)
LOGOUT_CONFIRM_BUTTONS = [[Button.inline("✅ Ha, uzish", b"logout_yes"), Button.inline("❌ Bekor qilish", b"logout_no")]]


def main_menu(user) -> list:
    active_label = "⏸ Pauza qilish" if user.is_active else "▶️ Davom ettirish"
    return [
        [Button.inline("➕ Kalit so'z qo'shish", b"add_kw"), Button.inline("➖ Kalit so'z o'chirish", b"del_kw")],
        [Button.inline("📋 Kalit so'zlar", b"list_kw")],
        [Button.inline("📊 Holat", b"status"), Button.inline(active_label, b"toggle_active")],
        [Button.inline("🗂 Kuzatiladigan guruhlar", b"groups_menu")],
        [Button.inline("🗑 Guruhni uzish", b"remove_group")],
        [Button.inline("🔌 Akkauntni uzish", b"logout_confirm")],
        [Button.inline("❓ Yordam", b"help")],
    ]


def format_status(user) -> str:
    kws = db_utils.list_keywords(user.tg_user_id)
    return "\n".join(
        [
            f"📱 Telefon: {user.phone or '-'}",
            f"📦 Buyurtma guruh: {user.order_group_id or 'ulanmagan'}",
            f"✅ Faol: {'ha' if user.is_active else 'yoq'}",
            f"🔑 Kalit so'zlar ({len(kws)}): {', '.join(kws) if kws else '-'}",
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


def register_handlers(bot_client: TelegramClient, manager) -> None:
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
        word = event.pattern_match.group(1)
        if not word:
            await event.respond("Foydalanish: /addkeyword taksi")
            return
        ok = db_utils.add_keyword(event.sender_id, word)
        await event.respond("✅ Qo'shildi." if ok else "Bu kalit so'z allaqachon mavjud yoki akkaunt ulanmagan.")

    @bot_client.on(events.NewMessage(pattern=r"/delkeyword(?: (.+))?", func=lambda e: e.is_private))
    async def delkeyword_handler(event):
        word = event.pattern_match.group(1)
        if not word:
            await event.respond("Foydalanish: /delkeyword taksi")
            return
        ok = db_utils.remove_keyword(event.sender_id, word)
        await event.respond("✅ O'chirildi." if ok else "Bunday kalit so'z topilmadi.")

    @bot_client.on(events.NewMessage(pattern="/keywords", func=lambda e: e.is_private))
    async def keywords_handler(event):
        kws = db_utils.list_keywords(event.sender_id)
        if kws:
            await event.respond("Kalit so'zlar:\n" + "\n".join(f"- {w}" for w in kws))
        else:
            await event.respond("Kalit so'zlar qo'shilmagan.")

    @bot_client.on(events.NewMessage(pattern="/pause", func=lambda e: e.is_private))
    async def pause_handler(event):
        db_utils.toggle_active(event.sender_id, False)
        await event.respond("⏸ Kuzatish to'xtatildi.")

    @bot_client.on(events.NewMessage(pattern="/resume", func=lambda e: e.is_private))
    async def resume_handler(event):
        db_utils.toggle_active(event.sender_id, True)
        user = db_utils.get_user(event.sender_id)
        if user and user.session_string:
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

        tg_user_id = event.sender_id
        user = db_utils.get_user(tg_user_id)
        if not user or not user.session_string:
            await event.answer("Avval /start bosib akkauntingizni ulang.", alert=True)
            return

        data = event.data

        if data == b"menu":
            user = db_utils.get_user(tg_user_id)
            await event.edit("Bosh menyu:", buttons=main_menu(user))

        elif data == b"help":
            await event.answer()
            await event.respond(HELP)

        elif data == b"status":
            await event.answer()
            await event.respond(format_status(user))

        elif data == b"toggle_active":
            new_active = not user.is_active
            db_utils.toggle_active(tg_user_id, new_active)
            if new_active:
                await manager.start_client_for_user(user)
            user = db_utils.get_user(tg_user_id)
            await event.answer("Holat yangilandi.")
            await event.edit("Bosh menyu:", buttons=main_menu(user))

        elif data == b"list_kw":
            kws = db_utils.list_keywords(tg_user_id)
            await event.answer()
            text = "Kalit so'zlar:\n" + "\n".join(f"- {w}" for w in kws) if kws else "Kalit so'zlar qo'shilmagan."
            await event.respond(text)

        elif data == b"add_kw":
            await event.answer()
            async with bot_client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message("Qo'shmoqchi bo'lgan kalit so'zni yuboring:")
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                word = resp.raw_text.strip()
                ok = db_utils.add_keyword(tg_user_id, word)
                await conv.send_message("✅ Qo'shildi." if ok else "Bu kalit so'z allaqachon mavjud.")

        elif data == b"del_kw":
            kws = db_utils.list_keywords(tg_user_id)
            if not kws:
                await event.answer("Kalit so'zlar yo'q.", alert=True)
                return
            buttons = [[Button.inline(f"❌ {w}", f"delkw:{w}".encode())] for w in kws]
            buttons.append([Button.inline("« Orqaga", b"menu")])
            await event.answer()
            await event.edit("O'chirmoqchi bo'lgan kalit so'zni tanlang:", buttons=buttons)

        elif data.startswith(b"delkw:"):
            word = data[len(b"delkw:"):].decode()
            db_utils.remove_keyword(tg_user_id, word)
            await event.answer(f"O'chirildi: {word}")
            kws = db_utils.list_keywords(tg_user_id)
            if kws:
                buttons = [[Button.inline(f"❌ {w}", f"delkw:{w}".encode())] for w in kws]
                buttons.append([Button.inline("« Orqaga", b"menu")])
                await event.edit("O'chirmoqchi bo'lgan kalit so'zni tanlang:", buttons=buttons)
            else:
                await event.edit("Kalit so'zlar qolmadi.", buttons=[[Button.inline("« Orqaga", b"menu")]])

        elif data == b"groups_menu":
            await event.answer()
            await send_groups_list(event.respond, manager, user)

        elif data.startswith(b"toggexc:"):
            chat_id = int(data[len(b"toggexc:"):])
            now_excluded = db_utils.toggle_excluded_group(user.id, chat_id)
            await event.answer("🔕 Kuzatishdan chiqarildi" if now_excluded else "🔔 Kuzatishga qo'shildi")

        elif data == b"remove_group":
            ok = db_utils.clear_order_group(tg_user_id)
            await event.answer("✅ Guruh uzildi." if ok else "Guruh ulanmagan edi.", alert=True)

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


async def run_login_flow(bot_client: TelegramClient, manager, chat_id: int, tg_user_id: int) -> None:
    try:
        async with bot_client.conversation(chat_id, timeout=300) as conv:
            await conv.send_message(WELCOME)
            phone_msg = await conv.get_response()
            phone = phone_msg.raw_text.strip()

            user_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await user_client.connect()

            try:
                sent = await user_client.send_code_request(phone)
            except PhoneNumberInvalidError:
                await conv.send_message("Telefon raqam noto'g'ri. Qaytadan /start bosing.")
                await user_client.disconnect()
                return

            await conv.send_message("Telegram sizga kod yubordi. Kodni kiriting:")
            code_msg = await conv.get_response()
            code = code_msg.raw_text.strip()

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
            user = db_utils.get_user(tg_user_id)
            await manager.start_client_for_user(user)

            await conv.send_message(
                "✅ Akkaunt ulandi!\n\n"
                "Endi buyurtmalar guruhini ulash uchun botni o'sha guruhga qo'shing "
                "va guruh ichida /setgroup buyrug'ini yuboring.\n\n"
                "Kalit so'zlarni tugmalar orqali ham boshqarishingiz mumkin:",
                buttons=main_menu(user),
            )
    except asyncio.TimeoutError:
        await bot_client.send_message(chat_id, "Vaqt tugadi. Qaytadan /start bosing.")
    except Exception:
        logger.exception("Login jarayonida xatolik: %s", tg_user_id)
        await bot_client.send_message(chat_id, "Xatolik yuz berdi. Qaytadan /start bosing.")
