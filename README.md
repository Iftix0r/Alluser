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
- **Pullik obuna va admin panel**: yangi foydalanuvchilarga avtomatik bepul sinov muddati beriladi, muddati tugagach kuzatish avtomatik to'xtaydi; admin `/admin` orqali foydalanuvchilarni ko'rib, obuna qo'shib/to'xtatib turadi.

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

`.env` faylini oching va quyidagilarni to'ldiring. `SESSION_ENCRYPTION_KEY` uchun kalit generatsiya qiling:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```
API_ID=123456
API_HASH=your_api_hash_here
BOT_TOKEN=123456:your_bot_token_here
DATABASE_URL=sqlite:///aluser.db
SESSION_ENCRYPTION_KEY=yuqoridagi_buyruqdan_olingan_kalit
ADMIN_IDS=123456789
```

`ADMIN_IDS` — admin panelga kirish huquqiga ega Telegram foydalanuvchi ID'lari (vergul bilan bir nechtasini yozish mumkin). O'z ID'ingizni bilish uchun [@userinfobot](https://t.me/userinfobot) ga yozing.

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

## Obuna va admin panel

- Akkaunt ulangan zahoti foydalanuvchiga avtomatik bepul sinov muddati beriladi (standart: 3 kun, `db_utils.TRIAL_DAYS`).
- Sinov muddati tugagach, kuzatish avtomatik to'xtaydi (har soatda tekshiriladi) va foydalanuvchiga xabar yuboriladi. U o'zi qayta yoqib ololmaydi — faqat admin obuna qo'shsa, xizmat qayta ishga tushadi.
- To'lovni tashqarida (karta, Payme/Click havolasi va h.k.) qabul qilib, admin quyidagicha tasdiqlaydi:
  1. `/admin` buyrug'ini yuboring (faqat `ADMIN_IDS`dagilar uchun ishlaydi)
  2. "👥 Foydalanuvchilar" → kerakli foydalanuvchini tanlang
  3. "➕ 7 kun" yoki "➕ 30 kun" tugmasini bosing — obuna shuncha kunga uzayadi va xizmat avtomatik yoqiladi
- Admin foydalanuvchini istalgan vaqt qo'lda ham to'xtatishi/yoqishi mumkin ("⛔ To'xtatish" / "▶️ Yoqish" tugmasi) — bu obunadan qat'i nazar ishlaydi.
- "📊 Statistika" tugmasi orqali jami/faol/muddati tugagan foydalanuvchilar sonini ko'rish mumkin.

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
| `/admin` | *(faqat admin)* admin panelni ochish |

## Loyiha tuzilishi

```
config.py            — .env dan sozlamalarni o'qish
models.py             — SQLAlchemy modellari (User, Keyword, ExcludedGroup)
database.py           — DB engine va sessiya
db_utils.py            — DB bilan ishlash uchun yordamchi funksiyalar (shu jumladan obuna)
crypto_utils.py         — session-stringlarni shifrlash/deshifrlash (Fernet)
matcher.py             — kalit so'z va telefon raqamini matndan aniqlash
bot/handlers.py         — bot buyruqlari, login oqimi, tugmali menyu
bot/admin_handlers.py    — admin panel (foydalanuvchilar, obuna, statistika)
userbot/manager.py       — har bir foydalanuvchi uchun alohida userbot-klientlarni boshqarish, obuna sweep
main.py                — dastur kirish nuqtasi
```

## Xavfsizlik bo'yicha eslatma

Har bir foydalanuvchining Telethon session-stringi ma'lumotlar bazasida `SESSION_ENCRYPTION_KEY` bilan **shifrlangan** holda saqlanadi (Fernet/AES). Shunga qaramay:

- `SESSION_ENCRYPTION_KEY`ni hech qachon git'ga commit qilmang yoki oshkor qilmang — bu kalitni yo'qotsangiz, barcha foydalanuvchilar qayta `/start` orqali ulanishi kerak bo'ladi (sessiyalarni deshifrlab bo'lmay qoladi).
- `aluser.db` (yoki boshqa `DATABASE_URL`) faylini hech qachon ochiq joyga qo'ymang yoki git'ga commit qilmang (`.gitignore`da allaqachon istisno qilingan).
- Serverga kirishni cheklang.
