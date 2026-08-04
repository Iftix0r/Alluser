import re

PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,17}\d)")
MIN_PHONE_DIGITS = 9
MAX_PHONE_DIGITS = 15
MAX_ORDER_TEXT_LENGTH = 100
MIN_MEANINGFUL_LETTERS = 3
MAX_BLANK_LINES = 1
URL_RE = re.compile(r"(https?://|t\.me/|www\.)\S+", re.IGNORECASE)
LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "\U00002190-\U000021FF"
    "\U00002300-\U000023FF"
    "\U0000FE0F"
    "]+"
)


def extract_phone(text: str) -> str | None:
    if not text:
        return None
    for match in PHONE_RE.finditer(text):
        cleaned = re.sub(r"[\s\-()]", "", match.group(0))
        digits = re.sub(r"\D", "", cleaned)
        if MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
            return cleaned
    return None


def find_matched_keyword(text: str, keywords: list[str]) -> str | None:
    if not text or not keywords:
        return None
    lowered = text.lower()
    for kw in keywords:
        if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", lowered):
            return kw
    return None


def is_valid_order_text(text: str) -> bool:
    if not text or len(text) > MAX_ORDER_TEXT_LENGTH:
        return False
    if URL_RE.search(text):
        return False
    return True


def has_meaningful_text(text: str) -> bool:
    """Emoji, raqam yoki belgilardan iborat, real matn bo'lmagan xabarlarni chiqarib tashlash uchun."""
    return len(LETTER_RE.findall(text or "")) >= MIN_MEANINGFUL_LETTERS


def has_emoji(text: str) -> bool:
    return bool(EMOJI_RE.search(text or ""))


def has_excessive_blank_lines(text: str) -> bool:
    """Ko'p bo'sh qatorli, chiroyli formatlangan xabarlar odatda haydovchilarning
    reklama/e'lon postlari bo'ladi (masalan "joy bor" e'lonlari), haqiqiy yo'lovchi
    so'rovlari emas."""
    blank_count = sum(1 for line in (text or "").split("\n") if not line.strip())
    return blank_count > MAX_BLANK_LINES
