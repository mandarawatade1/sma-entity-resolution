"""Field normalization helpers used before matching and storage."""
import re

CANONICAL_FIELDS = ["name", "email", "phone", "address", "city", "state", "zip", "company"]

_WS_RE = re.compile(r"\s+")
_PHONE_STRIP_RE = re.compile(r"[^\d+]")
_ADDRESS_ABBR = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
    "road": "rd", "lane": "ln", "court": "ct", "place": "pl",
    "apartment": "apt", "suite": "ste", "floor": "fl",
}


def _clean_ws(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


def normalize_name(value: str) -> str:
    if not value:
        return ""
    value = value.lower()
    value = re.sub(r"[.,]", "", value)
    return _clean_ws(value)


def normalize_email(value: str) -> str:
    if not value:
        return ""
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    if not value:
        return ""
    digits = _PHONE_STRIP_RE.sub("", value)
    digits = digits.lstrip("+")
    # Keep last 10 digits so country-code variants (e.g. "+91" vs "0") still match.
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_address(value: str) -> str:
    if not value:
        return ""
    value = value.lower()
    value = re.sub(r"[.,#]", " ", value)
    words = _clean_ws(value).split(" ")
    words = [_ADDRESS_ABBR.get(w, w) for w in words]
    return " ".join(words)


def normalize_text(value: str) -> str:
    if not value:
        return ""
    return _clean_ws(value.lower())


NORMALIZERS = {
    "name": normalize_name,
    "email": normalize_email,
    "phone": normalize_phone,
    "address": normalize_address,
    "city": normalize_text,
    "state": normalize_text,
    "zip": lambda v: re.sub(r"\D", "", v or "")[:6],
    "company": normalize_name,
}


def normalize_record(record: dict) -> dict:
    """Apply the field-appropriate normalizer to every canonical field present."""
    normalized = {}
    for field in CANONICAL_FIELDS:
        raw = record.get(field, "")
        raw = "" if raw is None else str(raw)
        normalized[field] = NORMALIZERS.get(field, normalize_text)(raw)
    return normalized
