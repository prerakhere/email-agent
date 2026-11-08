from agent.nodes.blocks import render_email_blocks, strip_links
from agent.schemas import Email


def make_email(**kwargs) -> Email:
    defaults = {
        "id": "m1",
        "thread_id": "t1",
        "sender": "Bank <alerts@bank.com>",
        "subject": "Alert",
        "body_preview": "You spent Rs. 50.00",
    }
    return Email(**{**defaults, **kwargs})


def test_each_email_becomes_a_numbered_block_starting_at_one():
    text = render_email_blocks(
        [make_email(subject="first"), make_email(subject="second")], 500
    )
    assert "<email id=1>" in text and "<email id=2>" in text
    assert text.count("</email>") == 2 and text.index("first") < text.index("second")


def test_blocks_hold_the_real_sender_but_redacted_subject_and_body():
    email = make_email(
        subject="Your OTP is 4821",
        body_preview="Card 4111 1111 1111 1111 see https://bank.com/x?t=1 paid Rs. 125000.00",
    )
    text = render_email_blocks([email], 500)
    assert "From: Bank <alerts@bank.com>" in text
    assert "Subject: Your OTP is [REDACTED]" in text
    assert "[NUMBER]" in text and "[LINK:bank.com]" in text
    assert "Rs. 125000.00" in text  # amounts survive redaction
    assert "4111" not in text


def test_the_body_is_trimmed_after_redaction():
    text = render_email_blocks([make_email(body_preview="x" * 2000)], 300)
    assert "x" * 300 in text and "x" * 301 not in text


def test_links_written_by_a_model_are_removed_and_spaces_tidied():
    cleaned = strip_links("Pay at https://evil.example/x or www.evil.example now")
    assert "evil" not in cleaned and "http" not in cleaned
    assert cleaned == "Pay at or now"
    assert strip_links("  plain   text ") == "plain text"
