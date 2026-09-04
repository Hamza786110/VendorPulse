"""
contracts/models.py

"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field


class ExtractedContractFields(BaseModel):
    """
    This is the schema the LangChain output parser forces the LLM to fill in.
    Keep descriptions tight — they become part of the prompt via
    PydanticOutputParser.get_format_instructions().
    """

    renewal_date: Optional[date] = Field(
        default=None,
        description="The date the contract renews or expires, in YYYY-MM-DD format. "
        "Null if not stated in the text.",
    )
    auto_renew: Optional[bool] = Field(
        default=None,
        description="True if the contract auto-renews unless cancelled. "
        "False if it requires manual renewal. Null if unclear.",
    )
    cancellation_window_days: Optional[int] = Field(
        default=None,
        description="Number of days' notice required before renewal date to cancel "
        "without penalty. Null if not stated.",
    )
    pricing_amount: Optional[float] = Field(
        default=None, description="The contract price/fee as a number, no currency symbol."
    )
    pricing_currency: Optional[str] = Field(
        default=None, description="3-letter currency code, e.g. USD, EUR. Null if unclear."
    )
    pricing_frequency: Optional[str] = Field(
        default=None,
        description="Billing frequency: one of 'monthly', 'annual', 'one_time', 'other'.",
    )
    vendor_name: Optional[str] = Field(
        default=None, description="The vendor/counterparty name, if identifiable."
    )
    confidence_notes: Optional[str] = Field(
        default=None,
        description="Brief note on any field the model was unsure about, or null.",
    )


class ContractStatus:
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    EXTRACTION_FAILED = "extraction_failed"


class ContractDocument(BaseModel):
    """Shape of a contract record as stored in MongoDB."""

    id: Optional[str] = Field(default=None, alias="_id")
    filename: str
    file_path: str
    uploaded_by: str  # user id from auth
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = ContractStatus.UPLOADED
    raw_text: Optional[str] = None
    extracted: Optional[ExtractedContractFields] = None
    extraction_error: Optional[str] = None

    class Config:
        populate_by_name = True