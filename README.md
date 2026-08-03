# Aluser

Telegram userbot tizimi: foydalanuvchilar botga `/start` bosib o'z Telegram akkauntini ulaydi, buyurtmalar guruhini belgilaydi va kalit so'zlarni sozlaydi. Shundan so'ng tizim ularning a'zo bo'lgan guruhlaridagi xabarlarni kuzatib, kalit so'zga mos xabar chiqqanda yuboruvchining ismi, username'i, telefon raqami (agar matnda bo'lsa), xabar matni va boshqa kerakli ma'lumotlarni avtomatik ravishda buyurtmalar guruhiga jo'natadi.

## Xususiyatlar

- **Ko'p foydalanuvchili**: har kim botga `/start` bosib mustaqil ravishda o'z akkauntini ulaydi; har birining kalit so'zlari, buyurtma guruhi va holati bir-biridan mustaqil.
- **Tugmali menyu**: kalit so'z qo'shish/o'chirish, holatni ko'rish, pauza/davom ettirish, guruhlarni boshqarish — hammasi inline tugmalar orqali (matnli buyruqlar ham ishlaydi).
- **Kalit so'z bo'yicha aniqlash**: xabar matnidan kalit so'z va telefon raqami (regex bilan) ajratib olinadi.
- **Guruhlarni tanlab kuzatish**: `/groups` orqali istalmagan guruhlarni kuzatishdan chiqarib qo'yish mumkin.
- **Flood-himoya**: bir foydalanuvchidan daqiqasiga 20 tadan ortiq buyurtma o'tsa, qolganlari o'tkazib yuboriladi (spam va flood-limitning oldini olish uchun).
- **Sessiya nazorati**: akkaunt sessiyasi bekor bo'lsa (masalan, boshqa joydan chiqib ketilsa), tizim buni aniqlab, foydalanuvchiga bot orqali xabar beradi.
- **Akkaunt/guruhni uzish**: `/logout` (tasdiqlash bilan) va `/removegroup` orqali bekor qilish mumkin.

## Talablar

- Python 3.10+
- Telegram API ma'lumotlari: `API_ID` va `API_HASH` — https://my.telegram.org dan olinadi
- Bot tokeni — [@BotFather](https://t.me/BotFather) orqali yaratiladi

## O'rnatish

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` faylini oching va quyidagilarni to'ldiring:

```
API_ID=123456
API_HASH=your_api_hash_here
BOT_TOKEN=123456:your_bot_token_here
DATABASE_URL=sqlite:///aluser.db
```

Ishga tushirish:

```bash
python3 main.py
```

## Foydalanish oqimi

1. Foydalanuvchi botga `/start` yozadi → "📱 Telefon raqamni yuborish" tugmasini bosadi (yoki raqamni qo'lda yozadi) → Telegram yuborgan SMS kodni kiritadi → (agar 2FA yoqilgan bo'lsa) parolni kiritadi. Shundan so'ng akkaunt ulanadi va tugmali bosh menyu ochiladi.
2. Botni buyurtmalar qabul qilinadigan guruhga qo'shib, o'sha guruh ichida `/setgroup` buyrug'ini yuboradi.
3. "➕ Kalit so'z qo'shish" tugmasi (yoki `/addkeyword taksi`) orqali kalit so'zlarni qo'shadi.
4. Ixtiyoriy: "🗂 Kuzatiladigan guruhlar" orqali qaysi guruhlar kuzatilishini tanlaydi.
5. Shundan keyin akkaunt a'zo bo'lgan guruhlarda kalit so'zga mos xabar chiqsa, bot avtomatik ravishda ism, username, telefon (topilsa), xabar havolasi, mijoz profiliga tezkor havola va xabar matnini buyurtmalar guruhiga yuboradi.

## Buyruqlar

| Buyruq | Tavsif |
|---|---|
| `/start` | Akkauntni ulash / bosh menyuni ochish |
| `/menu` | Tugmali bosh menyu |
| `/status` | Holatni ko'rish |
| `/addkeyword <so'z>` | Kalit so'z qo'shish |
| `/delkeyword <so'z>` | Kalit so'zni o'chirish |
| `/keywords` | Kalit so'zlar ro'yxati |
| `/groups` | Kuzatiladigan guruhlarni boshqarish |
| `/pause` | Kuzatishni to'xtatish |
| `/resume` | Kuzatishni davom ettirish |
| `/removegroup` | Buyurtmalar guruhini uzish |
| `/logout` | Akkauntni uzish (tasdiqlash bilan) |
| `/setgroup` | *(guruh ichida)* shu guruhni buyurtmalar guruhi qilib belgilash |

## Loyiha tuzilishi

```
config.py            — .env dan sozlamalarni o'qish
models.py             — SQLAlchemy modellari (User, Keyword, ExcludedGroup)
database.py           — DB engine va sessiya
db_utils.py            — DB bilan ishlash uchun yordamchi funksiyalar
matcher.py             — kalit so'z va telefon raqamini matndan aniqlash
bot/handlers.py         — bot buyruqlari, login oqimi, tugmali menyu
userbot/manager.py       — har bir foydalanuvchi uchun alohida userbot-klientlarni boshqarish
main.py                — dastur kirish nuqtasi
```

## Xavfsizlik bo'yicha eslatma

Har bir foydalanuvchining Telethon session-stringi ma'lumotlar bazasida **shifrlanmagan** holda saqlanadi (loyiha shu tarzda so'ralgan edi). Bu string amalda o'sha Telegram akkauntga to'liq kirish huquqini beradi, shuning uchun:

- `aluser.db` (yoki boshqa `DATABASE_URL`) faylini hech qachon ochiq joyga qo'ymang yoki git'ga commit qilmang (`.gitignore`da allaqachon istisno qilingan).
- Serverga kirishni cheklang.
- Production muhitda session-stringlarni shifrlash tavsiya etiladi — kerak bo'lsa, buni alohida qo'shib berish mumkin.
