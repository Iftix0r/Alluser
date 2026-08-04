import re

PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,17}\d)")
MIN_PHONE_DIGITS = 9
MAX_PHONE_DIGITS = 15
MAX_ORDER_TEXT_LENGTH = 100
URL_RE = re.compile(r"(https?://|t\.me/|www\.)\S+", re.IGNORECASE)


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
