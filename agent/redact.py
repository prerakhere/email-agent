"""Local redaction of sensitive-looking values BEFORE any text is sent to the LLM.

Runs on this machine, so masked values never leave it. Deliberately conservative: it masks
long digit runs, card/Aadhaar/phone-style groups, PAN numbers, secrets after words like OTP,
and URL paths/queries (which often carry tokens). Amounts and dates are left alone because the
classifier needs them. It also strips invisible characters. Regexes are a first layer, not a
guarantee.
"""

import re

# Zero-width / formatting characters that marketing mail uses as invisible "preheader" padding
# (they waste tokens and push real text out of the preview window). Built from code points so
# this source file stays plain ASCII: soft hyphen, combining grapheme joiner, zero-width and
# direction marks, bidi embeddings, word joiner and friends, bidi isolates, and the BOM.
_INVISIBLE_RANGES = [
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x2069),
    (0xFEFF, 0xFEFF),
]
_INVISIBLE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _INVISIBLE_RANGES) + "]"
)
_SPACE_RUNS = re.compile(r"[ \t]{2,}")

_URL = re.compile(r"https?://([^\s/<>\"')]+)[^\s<>\"')]*")
# Keyword, optional separator/"is", then a token that contains a digit (so "OTP with anyone" is untouched).
_SECRET = re.compile(
    r"\b(otp|pin|cvv|cvc|passcode|password)\b([\s:=-]*(?:is\s+)?)(?=\S*\d)\S+",
    re.IGNORECASE,
)
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_GROUPED = re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}(?:[ -]\d{1,4})?\b")  # cards, Aadhaar
_PHONE = re.compile(r"\b\d{5}[ -]\d{5}\b")
_LONG_DIGITS = re.compile(r"\d{6,}")


def redact(text: str) -> str:
    # Strip invisible characters first so they can't split a number to dodge the masks below.
    text = _SPACE_RUNS.sub(" ", _INVISIBLE.sub("", text))
    text = _URL.sub(r"[LINK:\1]", text)
    text = _SECRET.sub(r"\1\2[REDACTED]", text)
    text = _PAN.sub("[PAN]", text)
    text = _GROUPED.sub("[NUMBER]", text)
    text = _PHONE.sub("[NUMBER]", text)
    return _LONG_DIGITS.sub("[NUMBER]", text)
