from langchain_core.runnables import RunnableLambda

from agent.nodes.classify import LLMClassification, classify
from agent.redact import redact
from agent.schemas import Category, Email

# Invisible characters, named so the source file contains no hidden characters itself.
ZWSP = chr(0x200B)  # zero-width space
ZWNJ = chr(0x200C)  # zero-width non-joiner
ZWJ = chr(0x200D)  # zero-width joiner
LRM = chr(0x200E)  # left-to-right mark
BOM = chr(0xFEFF)  # byte order mark / zero-width no-break space
SHY = chr(0x00AD)  # soft hyphen
WJ = chr(0x2060)  # word joiner
RLO = chr(0x202E)  # right-to-left override


def test_long_digit_runs_are_masked():
    assert redact("Account 123456789012 debited") == "Account [NUMBER] debited"
    assert redact("Your code 482913") == "Your code [NUMBER]"


def test_card_style_groups_are_masked():
    assert redact("Card 4111 1111 1111 1111 used") == "Card [NUMBER] used"
    assert redact("Card 4111-1111-1111-1111 used") == "Card [NUMBER] used"


def test_aadhaar_style_groups_are_masked():
    assert redact("ID 1234 5678 9012") == "ID [NUMBER]"


def test_phone_number_split_in_two_groups_is_masked():
    assert redact("Call 98765 43210 now") == "Call [NUMBER] now"


def test_pan_number_is_masked():
    assert redact("PAN ABCDE1234F on file") == "PAN [PAN] on file"


def test_value_after_otp_pin_cvv_password_is_masked_even_when_short():
    assert redact("Your OTP is 4821") == "Your OTP is [REDACTED]"
    assert redact("PIN: 1234") == "PIN: [REDACTED]"
    assert redact("password: hunter2") == "password: [REDACTED]"
    assert redact("CVV 123") == "CVV [REDACTED]"


def test_keyword_without_a_secret_is_left_alone():
    assert (
        redact("Do not share your OTP with anyone")
        == "Do not share your OTP with anyone"
    )


def test_urls_keep_only_the_domain():
    text = "Reset here https://accounts.example.com/reset?token=abc123 now"
    assert redact(text) == "Reset here [LINK:accounts.example.com] now"


def test_amounts_dates_and_plain_text_are_untouched():
    text = "Rs 1,250.00 due on 05-Nov-2026 (2026-11-05), invoice #42"
    assert redact(text) == text


def test_empty_and_already_redacted_text_are_stable():
    assert redact("") == ""
    once = redact("OTP is 4821 and card 4111 1111 1111 1111")
    assert redact(once) == once


# ---- invisible characters (marketing "preheader" padding) ----


def test_zero_width_characters_are_removed():
    assert redact(f"Hel{ZWSP}lo{ZWNJ}{ZWJ}{BOM}") == "Hello"


def test_other_invisible_characters_are_removed():
    assert redact(f"a{SHY}b{LRM}{WJ}c{RLO}d") == "abcd"


def test_padding_made_of_invisible_characters_collapses_to_one_space():
    pad = f"{ZWNJ}{ZWSP}"
    assert redact(f"Subject {pad} {pad} {pad} end") == "Subject end"


def test_hidden_characters_cannot_split_a_number_to_dodge_masking():
    assert redact(f"Card 4111{ZWSP}1111{ZWSP}1111{ZWSP}1111") == "Card [NUMBER]"


def test_newlines_and_normal_non_ascii_text_are_preserved():
    text = "Résumé — 你好 😀 ₹500\n\nnext line"
    assert redact(text) == text


# ---- wiring: classify must redact subject and body, but not the sender ----


def test_classify_sends_redacted_subject_and_body_but_real_sender():
    seen = {}

    def capture(inputs):
        seen.update(inputs)
        return LLMClassification(
            category=Category.NOTIFICATIONS, confidence=0.9, reason="r"
        )

    email = Email(
        id="1",
        thread_id="t",
        sender="Bank <alerts@bank.com>",
        subject="Your OTP is 4821",
        body_preview="Card 4111 1111 1111 1111 see https://bank.com/x?t=1",
    )
    classify(email, RunnableLambda(capture))
    assert seen["sender"] == "Bank <alerts@bank.com>"
    assert seen["subject"] == "Your OTP is [REDACTED]"
    assert seen["body_preview"] == "Card [NUMBER] see [LINK:bank.com]"
