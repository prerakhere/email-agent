"""LLM classification for mail the prefilter could not decide.

Built from LangChain pieces: a ChatPromptTemplate piped (LCEL `|`) into a chat model whose
reply is forced into a typed shape via `with_structured_output`.
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from agent.redact import redact
from agent.schemas import Category, Classification, Email

BODY_CHARS = 500  # cost control: the model only sees the start of the body
DEFAULT_THRESHOLD = 0.7

SYSTEM_PROMPT = """You triage one personal email into exactly one category.
Allowed categories (use the exact value):
{categories}

Guidance:
- bills: statements or invoices with an amount and due date (cards, utilities, subscriptions).
- receipts: order or payment confirmations needing no action.
- newsletters: recurring content you subscribed to.
- promotions: marketing and offers from stores or banks.
- important: a real person wrote to the user, or there is a deadline or consequence
  (security, tax, travel, government, money).
- notifications: automated social or app pings (GitHub, LinkedIn, calendar).
- job_alerts: job listings and recruiter alerts.
- needs_review: nothing fits well.
If a mail is a bill and also a promotion, prefer bills over important over receipts over the rest.
When unsure between important and noise, choose important: wrongly hiding real mail is worse.
Give a confidence from 0 to 1 and a one-sentence reason."""

HUMAN_PROMPT = """From: {sender}
Subject: {subject}
Has unsubscribe header: {has_unsubscribe}
Body start:
{body_preview}"""

PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
).partial(categories=", ".join(c.value for c in Category))


class LLMClassification(BaseModel):
    """The shape the model must reply in (no `source`; we add that ourselves)."""

    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


def build_classifier(llm) -> Runnable:
    """prompt | model-with-structured-output, as one runnable chain."""
    return PROMPT | llm.with_structured_output(LLMClassification)


def classify(
    email: Email, chain: Runnable, threshold: float = DEFAULT_THRESHOLD
) -> Classification:
    answer: LLMClassification = chain.invoke(
        {
            "sender": email.sender,
            "subject": redact(email.subject),
            "has_unsubscribe": "yes" if email.list_unsubscribe else "no",
            # Redact first, then trim, so a number cut at the boundary can't leak partial digits.
            "body_preview": redact(email.body_preview)[:BODY_CHARS],
        }
    )
    if answer.confidence < threshold:
        return Classification(
            category=Category.NEEDS_REVIEW,
            confidence=answer.confidence,
            reason=f"low confidence; model guessed {answer.category.value}: {answer.reason}",
            source="llm",
        )
    return Classification(
        category=answer.category,
        confidence=answer.confidence,
        reason=answer.reason,
        source="llm",
    )
