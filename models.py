"""Pydantic models for API request validation and response serialisation.

Request models validate incoming JSON payloads (replacing raw json.loads()).
Response models document the API contract and let FastAPI auto-serialise.
"""

import json
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Invoice data — request validation
# ---------------------------------------------------------------------------

class PatientInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    address: str = ""
    postcode: str = ""


class LineItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str = ""
    our_ref: str = ""
    client_ref: str = ""
    mob: str = ""
    miles: str = ""
    wait_pounds: str = ""
    miles_pounds: str = ""
    job_pounds: str = ""
    total: str = ""
    charged: str = ""
    nhs_number: str = ""
    contract_hospital: str = ""
    booked_by: str = ""
    from_location: str = ""
    to_location: str = ""
    status: str = ""
    directions: str = ""
    wait_notes: str = ""


class InvoiceHeader(BaseModel):
    model_config = ConfigDict(extra="allow")
    number: str = ""
    date: str = ""
    account_ref: str = ""
    ref: str = ""
    po_number: str = ""
    payment_terms: str = ""
    period: str = ""
    items: list[LineItem] = []


class FinancialInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    net: str = ""
    net_label: str = "net"
    discount: str = ""
    discount_label: str = "discount"
    subtotal: str = ""
    subtotal_label: str = "Invoice subtotal"
    vat_amount: str = ""
    vat_label: str = "VAT"
    vat_percentage: str = "20"
    total: str = ""
    total_label: str = "TOTAL DUE"


class BankDetails(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    account_name: str = ""
    account_number: str = ""
    sort_code: str = ""


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_price_flat: str = ""
    mileage_included: str = ""
    mileage_charge: str = ""


class InvoiceData(BaseModel):
    """Full invoice data structure received from the frontend."""
    model_config = ConfigDict(extra="allow")
    patient: PatientInfo = PatientInfo()
    invoice: InvoiceHeader = InvoiceHeader()
    financial: FinancialInfo = FinancialInfo()
    bank: BankDetails = BankDetails()
    paid: bool = False
    style: str = "style1"
    item_name: str = ""
    pricing: Optional[PricingConfig] = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ConversionResponse(BaseModel):
    session_id: str
    base_name: str
    file_count: int
    files: list[str]


class MergeResponse(BaseModel):
    session_id: str
    base_name: str
    filename: str
    file_count: int
    files: list[str]
    total_rows: int


class CombinedSessionResponse(BaseModel):
    session_id: str
    file_count: int
    files: list[str]


class InvoiceEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str
    filename: str
    invoice_data: dict[str, Any]
    source_headers: list[str] = []
    index: int


class BatchInvoicesResponse(BaseModel):
    batch_session_id: str
    invoices: list[InvoiceEntry]
    total_count: int


class UploadHtmlResponse(BaseModel):
    session_id: str
    filename: str
    invoice_data: dict[str, Any]


class SummaryTemplateUploadResponse(BaseModel):
    columns: list[str]
    template_filename: Optional[str] = None


class SummaryMappingResponse(BaseModel):
    ok: bool


class SummaryTemplateStatusResponse(BaseModel):
    has_template: bool
    has_mapping: bool
    columns: list[str] = []
    mapping: dict[str, str] = {}
    template_filename: Optional[str] = None


class CalculatedField(BaseModel):
    id: str
    label: str


class CalculatedFieldsResponse(BaseModel):
    fields: list[CalculatedField]


# ---------------------------------------------------------------------------
# Parse helpers — validated replacements for raw json.loads()
# ---------------------------------------------------------------------------

def parse_invoice_data(raw_json: str) -> dict:
    """Parse and validate incoming invoice data JSON, returning a plain dict."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid invoice data JSON: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invoice data must be a JSON object")
    validated = InvoiceData.model_validate(data)
    return validated.model_dump()


def parse_json_string_list(raw_json: str, field_name: str = "data") -> list[str]:
    """Parse a JSON string expected to contain a list of strings."""
    try:
        result = json.loads(raw_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")
    if not isinstance(result, list):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON array")
    return result


def parse_json_dict(raw_json: str, field_name: str = "data") -> dict:
    """Parse a JSON string expected to contain an object/dict."""
    try:
        result = json.loads(raw_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} JSON format")
    if not isinstance(result, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON object")
    return result
