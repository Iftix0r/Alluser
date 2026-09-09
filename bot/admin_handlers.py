import asyncio
import logging
from datetime import datetime, timedelta

from telethon import TelegramClient, events
from telethon.errors import AlreadyInConversationError, RPCError
from telethon.tl.custom import Button

import db_utils
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

USERS_PAGE_SIZE = 8

GENERIC_ADMIN_ERROR_TEXT = "Xatolik yuz berdi."
ADMIN_BUSY_TEXT = "Avvalgi amal hali tugallanmagan. Birozdan so'ng qayta urinib ko'ring."


def _is_admin(event) -> bool:
    return event.sender_id in ADMIN_IDS


def _user_row_label(user) -> str:
    status = "✅" if user.is_active and db_utils.is_subscription_active(user) else "⛔"
    phone = user.phone or str(user.tg_user_id)
    return f"{status} {phone} — {db_utils.format_subscription_status(user)}"


def admin_menu_buttons() -> list:
    return [
        [Button.inline("👥 Foydalanuvchilar", b"admin_users:0")],
        [Button.inline("🔍 Qidirish", b"admin_search")],
        [Button.inline("⏳ Muddati tugayotganlar", b"admin_expiring")],
        [Button.inline("📢 Xabar yuborish", b"admin_broadcast")],
        [Button.inline("📊 Statistika", b"admin_stats")],
    ]


def _users_page_buttons(users, page: int) -> list:
    start = page * USERS_PAGE_SIZE
    chunk = users[start : start + USERS_PAGE_SIZE]
    buttons = [[Button.inline(_user_row_label(u), f"admin_user:{u.id}".encode())] for u in chunk]

    nav = []
    if page > 0:
        nav.append(Button.inline("« Oldingi", f"admin_users:{page - 1}".encode()))
    if start + USERS_PAGE_SIZE < len(users):
        nav.append(Button.inline("Keyingi »", f"admin_users:{page + 1}".encode()))
    if nav:
        buttons.append(nav)

    buttons.append([Button.inline("« Admin menyu", b"admin_menu")])
    return buttons


def _user_detail_text(user) -> str:
    created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "-"
    orders_total = db_utils.count_orders(user.id)
    orders_today = db_utils.count_orders(user.id, since=_today_start())
    extra_groups = len(db_utils.list_extra_order_groups(user.id))
    extra_accounts = len(db_utils.list_extra_accounts_by_user_db_id(user.id))
    return (
        f"👤 Foydalanuvchi ID: {user.tg_user_id}\n"
        f"📱 Telefon: {user.phone or '-'}\n"
        f"📦 Buyurtma guruh: {user.order_group_id or 'ulanmagan'} (+{extra_groups} qo'shimcha)\n"
        f"👥 Qo'shimcha akkauntlar: {extra_accounts}\n"
        f"✅ Faol: {'ha' if user.is_active else 'yoq'}\n"
        f"💳 Obuna: {db_utils.format_subscription_status(user)}\n"
        f"📦 Buyurtmalar: bugun {orders_today} ta, jami {orders_total} ta\n"
        f"📅 Ro'yxatdan o'tgan: {created}"
    )


def _user_detail_buttons(user) -> list:
    active_label = "⛔ To'xtatish" if user.is_active else "▶️ Yoqish"
    active_style = "danger" if user.is_active else "success"
    return [
        [
            Button.inline("➕ 7 kun", f"admin_ext:{user.id}:7".encode(), style="success"),
            Button.inline("➕ 30 kun", f"admin_ext:{user.id}:30".encode(), style="success"),
        ],
        [Button.inline("✏️ Boshqa muddat", f"admin_ext_custom:{user.id}".encode())],
        [
            Button.inline("♾ Cheksiz obuna", f"admin_unlimited:{user.id}".encode(), style="success"),
            Button.inline("🛑 Obunani bekor qilish", f"admin_revoke:{user.id}".encode(), style="danger"),
        ],
        [Button.inline(active_label, f"admin_toggle:{user.id}".encode(), style=active_style)],
        [Button.inline("✉️ Xabar yuborish", f"admin_msg:{user.id}".encode())],
        [Button.inline("🔌 Sessiyani tozalash", f"admin_clear_session:{user.id}".encode(), style="danger")],
        [Button.inline("🗑 Foydalanuvchini o'chirish", f"admin_delete_confirm:{user.id}".encode(), style="danger")],
        [Button.inline("« Ro'yxatga qaytish", b"admin_users:0")],
    ]


def _today_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def register_admin_handlers(bot_client: TelegramClient, manager) -> None:
    @bot_client.on(events.NewMessage(pattern="/admin", func=lambda e: e.is_private and _is_admin(e)))
    async def admin_handler(event):
        await event.respond("🛠 Admin panel:", buttons=admin_menu_buttons())

    @bot_client.on(events.CallbackQuery(pattern=b"admin_"))
    async def admin_callback_handler(event):
        if not _is_admin(event):
            await event.answer("Ruxsat yo'q.", alert=True)
            return
        try:
            await _dispatch_admin_callback(event, manager)
        except Exception:
            logger.exception("Admin callbackda xatolik: data=%s", event.data)
            try:
                await event.answer(GENERIC_ADMIN_ERROR_TEXT, alert=True)
            except Exception:
                await event.respond(GENERIC_ADMIN_ERROR_TEXT)


async def _dispatch_admin_callback(event, manager) -> None:
    data = event.data

    if data == b"admin_menu":
        await event.edit("🛠 Admin panel:", buttons=admin_menu_buttons())

    elif data == b"admin_stats":
        users = db_utils.get_all_users()
        connected = [u for u in users if u.session_string]
        active = sum(1 for u in connected if u.is_active and db_utils.is_subscription_active(u))
        expired = sum(1 for u in connected if not db_utils.is_subscription_active(u))
        order_stats = db_utils.get_global_order_stats()
        top_users = db_utils.get_top_order_users(limit=5, since=datetime.utcnow() - timedelta(days=7))
        lines = [
            "📊 Statistika:\n",
            f"Jami ro'yxatdan o'tganlar: {len(users)}",
            f"Akkaunt ulaganlar: {len(connected)}",
            f"Hozir faol (obunasi bor): {active}",
            f"Obunasi tugaganlar: {expired}",
            "",
            f"📦 Buyurtmalar — bugun: {order_stats['today']}, "
            f"7 kunda: {order_stats['week']}, jami: {order_stats['total']}",
        ]
        if top_users:
            lines.append("\n🏆 Oxirgi 7 kunda eng faol foydalanuvchilar:")
            for user_id, cnt in top_users:
                u = db_utils.find_user_by_id(user_id)
                label = u.phone or str(u.tg_user_id) if u else str(user_id)
                lines.append(f"- {label}: {cnt} ta buyurtma")
        await event.answer()
        await event.respond("\n".join(lines))

    elif data == b"admin_search":
        await event.answer()
        try:
            async with event.client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message("Qidirish uchun telefon raqami yoki foydalanuvchi ID sini yuboring:")
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                results = db_utils.search_users(resp.raw_text.strip())
                if not results:
                    await conv.send_message("Hech narsa topilmadi.")
                    return
                buttons = [[Button.inline(_user_row_label(u), f"admin_user:{u.id}".encode())] for u in results[:20]]
                buttons.append([Button.inline("« Admin menyu", b"admin_menu")])
                await conv.send_message(f"🔍 Topildi ({len(results)}):", buttons=buttons)
        except AlreadyInConversationError:
            await event.respond(ADMIN_BUSY_TEXT)

    elif data == b"admin_expiring":
        users = db_utils.get_expiring_soon_users(3)
        await event.answer()
        if not users:
            await event.respond("Yaqin 3 kun ichida muddati tugaydiganlar yo'q.")
            return
        buttons = [[Button.inline(_user_row_label(u), f"admin_user:{u.id}".encode())] for u in users]
        buttons.append([Button.inline("« Admin menyu", b"admin_menu")])
        await event.respond(f"⏳ Muddati 3 kun ichida tugaydi ({len(users)}):", buttons=buttons)

    elif data == b"admin_broadcast":
        await event.answer()
        try:
            async with event.client.conversation(event.chat_id, timeout=300) as conv:
                await conv.send_message("Barcha ulangan foydalanuvchilarga yuboriladigan xabarni yozing:")
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                broadcast_text = resp.raw_text
                targets = [u for u in db_utils.get_all_users() if u.session_string]
                await conv.send_message(
                    f"Quyidagi xabar {len(targets)} ta foydalanuvchiga yuboriladi:\n\n"
                    f"{broadcast_text}\n\nTasdiqlash uchun HA deb yozing:"
                )
                try:
                    confirm = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi, bekor qilindi.")
                    return
                if confirm.raw_text.strip().lower() not in ("ha", "ha.", "yes"):
                    await conv.send_message("Bekor qilindi.")
                    return
                sent = 0
                for target in targets:
                    try:
                        await event.client.send_message(target.tg_user_id, broadcast_text, parse_mode=None)
                        sent += 1
                    except RPCError:
                        logger.warning("Broadcast yuborilmadi: %s", target.tg_user_id)
                    await asyncio.sleep(0.05)
                await conv.send_message(f"✅ Yuborildi: {sent}/{len(targets)}")
        except AlreadyInConversationError:
            await event.respond(ADMIN_BUSY_TEXT)

    elif data.startswith(b"admin_ext_custom:"):
        user_id = int(data[len(b"admin_ext_custom:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        await event.answer()
        try:
            async with event.client.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message("Necha kunga uzaytirish kerak? Raqam yuboring (masalan: 14):")
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                try:
                    days = int(resp.raw_text.strip())
                except ValueError:
                    await conv.send_message("Noto'g'ri son.")
                    return
                user = db_utils.extend_subscription(target.tg_user_id, days)
                if user.session_string:
                    await manager.start_client_for_user(user)
                await manager.notify(user.tg_user_id, f"✅ Obunangizga {days} kun qo'shildi. Rahmat!")
                await conv.send_message(
                    f"✅ {days} kun qo'shildi.\n\n{_user_detail_text(user)}",
                    buttons=_user_detail_buttons(user),
                )
        except AlreadyInConversationError:
            await event.respond(ADMIN_BUSY_TEXT)

    elif data.startswith(b"admin_unlimited:"):
        user_id = int(data[len(b"admin_unlimited:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        user = db_utils.set_unlimited_subscription(target.tg_user_id)
        if user.session_string:
            await manager.start_client_for_user(user)
        await manager.notify(user.tg_user_id, "🎉 Sizga muddatsiz (cheksiz) obuna berildi!")
        await event.answer("♾ Cheksiz obuna berildi.")
        await event.edit(_user_detail_text(user), buttons=_user_detail_buttons(user))

    elif data.startswith(b"admin_revoke:"):
        user_id = int(data[len(b"admin_revoke:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        user = db_utils.revoke_subscription(target.tg_user_id)
        await manager.stop_client_for_user(user.id)
        await manager.notify(
            user.tg_user_id,
            "⛔ Obunangiz admin tomonidan bekor qilindi. Davom ettirish uchun admin bilan bog'laning.",
        )
        await event.answer("🛑 Obuna bekor qilindi.")
        await event.edit(_user_detail_text(user), buttons=_user_detail_buttons(user))

    elif data.startswith(b"admin_msg:"):
        user_id = int(data[len(b"admin_msg:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        await event.answer()
        try:
            async with event.client.conversation(event.chat_id, timeout=180) as conv:
                await conv.send_message(
                    f"{target.phone or target.tg_user_id} ga yuboriladigan xabarni yozing:"
                )
                try:
                    resp = await conv.get_response()
                except asyncio.TimeoutError:
                    await conv.send_message("Vaqt tugadi.")
                    return
                try:
                    await event.client.send_message(target.tg_user_id, resp.raw_text, parse_mode=None)
                    await conv.send_message("✅ Xabar yuborildi.")
                except RPCError:
                    await conv.send_message("❌ Xabar yuborilmadi (foydalanuvchi botni bloklagan bo'lishi mumkin).")
        except AlreadyInConversationError:
            await event.respond(ADMIN_BUSY_TEXT)

    elif data.startswith(b"admin_delete_confirm:"):
        user_id = int(data[len(b"admin_delete_confirm:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        await event.answer()
        await event.edit(
            f"⚠️ {target.phone or target.tg_user_id} butunlay o'chirilsinmi? Bu amalni bekor qilib "
            "bo'lmaydi — barcha kalit so'zlar, guruhlar va sozlamalar yo'qoladi.",
            buttons=[
                [
                    Button.inline("✅ Ha, o'chirish", f"admin_delete:{user_id}".encode(), style="danger"),
                    Button.inline("❌ Bekor qilish", f"admin_user:{user_id}".encode()),
                ]
            ],
        )

    elif data.startswith(b"admin_delete:"):
        user_id = int(data[len(b"admin_delete:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        await manager.stop_client_for_user(target.id)
        db_utils.delete_user(target.id)
        await event.answer("🗑 O'chirildi.")
        await event.edit(
            f"🗑 {target.phone or target.tg_user_id} butunlay o'chirildi.",
            buttons=[[Button.inline("« Ro'yxatga qaytish", b"admin_users:0")]],
        )

    elif data.startswith(b"admin_clear_session:"):
        user_id = int(data[len(b"admin_clear_session:") :])
        target = db_utils.find_user_by_id(user_id)
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        await manager.stop_client_for_user(target.id)
        db_utils.clear_session(target.tg_user_id)
        await manager.notify(
            target.tg_user_id,
            "⚠️ Sessiyangiz admin tomonidan tozalandi. Qayta ulanish uchun /start bosing.",
        )
        await event.answer("Sessiya tozalandi.")
        user = db_utils.find_user_by_id(user_id)
        await event.respond(
            f"🔌 Sessiya tozalandi, foydalanuvchi qayta ulanishi kerak.\n\n{_user_detail_text(user)}",
            buttons=[[Button.inline("« Ro'yxatga qaytish", b"admin_users:0")]],
        )

    elif data.startswith(b"admin_users:"):
        page = int(data[len(b"admin_users:") :])
        users = [u for u in db_utils.get_all_users() if u.session_string]
        if not users:
            await event.answer("Foydalanuvchilar yo'q.", alert=True)
            return
        await event.answer()
        await event.edit(f"👥 Foydalanuvchilar ({len(users)}):", buttons=_users_page_buttons(users, page))

    elif data.startswith(b"admin_user:"):
        user_id = int(data[len(b"admin_user:") :])
        user = db_utils.find_user_by_id(user_id)
        if not user:
            await event.answer("Topilmadi.", alert=True)
            return
        await event.answer()
        await event.edit(_user_detail_text(user), buttons=_user_detail_buttons(user))

    elif data.startswith(b"admin_ext:"):
        _, user_id_s, days_s = data.decode().split(":")
        target = db_utils.find_user_by_id(int(user_id_s))
        if not target:
            await event.answer("Topilmadi.", alert=True)
            return
        user = db_utils.extend_subscription(target.tg_user_id, int(days_s))
        if user.session_string:
            await manager.start_client_for_user(user)
        await manager.notify(user.tg_user_id, f"✅ Obunangizga {days_s} kun qo'shildi. Rahmat!")
        await event.answer(f"{days_s} kun qo'shildi.")
        await event.edit(_user_detail_text(user), buttons=_user_detail_buttons(user))

    elif data.startswith(b"admin_toggle:"):
        user_id = int(data[len(b"admin_toggle:") :])
        user = db_utils.find_user_by_id(user_id)
        if not user:
            await event.answer("Topilmadi.", alert=True)
            return
        new_active = not user.is_active
        db_utils.toggle_active(user.tg_user_id, new_active)
        if new_active and user.session_string:
            await manager.start_client_for_user(user)
        else:
            await manager.stop_client_for_user(user.id)
        note = (
            "▶️ Xizmatingiz admin tomonidan yoqildi."
            if new_active
            else "⛔ Xizmatingiz admin tomonidan to'xtatildi."
        )
        await manager.notify(user.tg_user_id, note)
        user = db_utils.find_user_by_id(user_id)
        await event.answer("Holat yangilandi.")
        await event.edit(_user_detail_text(user), buttons=_user_detail_buttons(user))
