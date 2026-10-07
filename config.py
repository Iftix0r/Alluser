import os

from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///aluser.db")
SESSION_ENCRYPTION_KEY = os.environ["SESSION_ENCRYPTION_KEY"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}

# Asosiy admin (biznes egasi) — mijozlarga tugmada ko'rsatiladi va obuna eslatmalari
# aynan shu odamga yuboriladi.
ADMIN_CONTACT_USERNAME = os.environ.get("ADMIN_CONTACT_USERNAME", "Iftix0r")
ADMIN_CONTACT_ID = int(os.environ.get("ADMIN_CONTACT_ID", "2114098498"))

# Bitta yuboruvchidan ketma-ket buyurtmalar orasidagi eng kam vaqt (soniyada).
# Shu vaqt ichida yana xabar kelsa, buyurtma sifatida qabul qilinmaydi.
SENDER_COOLDOWN_SECONDS = int(os.environ.get("SENDER_COOLDOWN_SECONDS", "180"))
