"""Core data models shared by every graph node."""

from datetime import date
from decimal import Decimal
from email.utils import parseaddr
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class Category(StrEnum):
    BILLS = "bills"
    RECEIPTS = "receipts"
    NEWSLETTERS = "newsletters"
    PROMOTIONS = "promotions"
    IMPORTANT = "important"
    NOTIFICATIONS = "notifications"
    JOB_ALERTS = "job_alerts"
    NEEDS_REVIEW = "needs_review"


class Email(BaseModel):
    id: str
    thread_id: str
    sender: str
    subject: str
    body_preview: str = ""
    list_unsubscribe: bool = False
    label_ids: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1].lower()

    @computed_field
    @property
    def sender_domain(self) -> str:
        return self.sender_address.rpartition("@")[2]

    @computed_field
    @property
    def is_starred(self) -> bool:
        return "STARRED" in self.label_ids

    @computed_field
    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.label_ids


class Classification(BaseModel):
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    source: Literal["rule", "llm"]


class Bill(BaseModel):
    vendor: str
    amount: Decimal = Field(gt=0)
    currency: str
    due_date: date | None = None
    confidence: float = Field(ge=0.0, le=1.0)
