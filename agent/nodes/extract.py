"""LLM extraction of bill/receipt details (biller, amount, currency, due date).

Same LangChain pattern as classify: a prompt piped into a chat model whose reply is forced into
a typed shape. Returns None when there is nothing safe to log; low-confidence answers are still
returned (with their confidence) so the caller can flag the row instead of silently dropping it.
"""

from datetime import date
from decimal import Decimal

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from agent.redact import redact
from agent.schemas import Bill, Email

BODY_CHARS = 1500  # more than classify: amounts often sit lower in the body

SYSTEM_PROMPT = """You read one bill or receipt email and extract its payment details.
- vendor: the company the money is owed to or was paid to (not the bank that sent the email
  unless the bank is the biller).
- amount: the total due (bill) or total paid (receipt) as a plain number, no symbols or commas.
  Use null if no amount is stated. Never guess.
- currency: ISO code such as INR or USD (the rupee symbol means INR).
- due_date: the payment due date as YYYY-MM-DD, or null (receipts usually have none).
Numbers shown as [NUMBER] are masked account details: ignore them.
Give a confidence from 0 to 1 for the amount and vendor."""

HUMAN_PROMPT = """From: {sender}
Subject: {subject}
Body start:
{body_preview}"""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
)


class LLMBill(BaseModel):
    """The shape the model must reply in. Plain float: structured output handles it reliably."""

    vendor: str
    amount: float | None = None
    currency: str
    due_date: date | None = None
    confidence: float = Field(ge=0.0, le=1.0)


def build_extractor(llm) -> Runnable:
    return PROMPT | llm.with_structured_output(LLMBill)


def build_bill_inputs(email: Email) -> dict[str, str]:
    """Exactly what leaves this machine for extraction (redacted; amounts kept)."""
    return {
        "sender": email.sender,
        "subject": redact(email.subject),
        "body_preview": redact(email.body_preview)[:BODY_CHARS],
    }


def extract_bill(email: Email, chain: Runnable) -> Bill | None:
    answer: LLMBill = chain.invoke(build_bill_inputs(email))
    currency = answer.currency.strip().upper()
    if answer.amount is None or answer.amount <= 0 or not currency:
        return None
    return Bill(
        vendor=answer.vendor.strip() or email.sender_address,
        amount=Decimal(str(answer.amount)),
        currency=currency,
        due_date=answer.due_date,
        confidence=answer.confidence,
    )
