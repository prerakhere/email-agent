"""Local redaction of sensitive-looking values BEFORE any text is sent to the LLM.

Runs on this machine, so masked values never leave it. Deliberately conservative: it masks
long digit runs, card/Aadhaar/phone-style groups, PAN numbers, secrets after words like OTP,
and URL paths/queries (which often carry tokens). Amounts and dates are left alone because the
classifier needs them. Regexes are a first layer, not a guarantee.
"""

import re

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
    text = _URL.sub(r"[LINK:\1]", text)
    text = _SECRET.sub(r"\1\2[REDACTED]", text)
    text = _PAN.sub("[PAN]", text)
    text = _GROUPED.sub("[NUMBER]", text)
    text = _PHONE.sub("[NUMBER]", text)
    return _LONG_DIGITS.sub("[NUMBER]", text)
