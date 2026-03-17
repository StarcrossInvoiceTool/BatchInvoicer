"""Summary-sheet building, line-item charge helpers, and calculated field definitions."""

import json
import logging
import math
import os
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Line-item charge helpers
# ---------------------------------------------------------------------------


def _parse_miles(miles_val) -> float:
    """Parse miles from item (string or number); return 0 if invalid."""
    if miles_val is None:
        return 0.0
    s = str(miles_val).strip().lower()
    if s in ("", "nan", "none"):
        return 0.0
    try:
        return float(miles_val)
    except (TypeError, ValueError):
        return 0.0


def ensure_line_item_charges(invoice_data: dict) -> None:
    """Fallback: fill EMPTY line-item charges from pricing config.

    Only used when loading from pickle (e.g. download-all) where the UI
    may not have saved values yet.  Never overwrites non-empty values.
    """
    pricing = invoice_data.get("pricing") or {}
    job_price = float(pricing.get("job_price_flat") or 0)
    mileage_included = float(pricing.get("mileage_included") or 0)
    mileage_charge = float(pricing.get("mileage_charge") or 0)

    items = (invoice_data.get("invoice") or {}).get("items") or []
    for item in items:
        if not str(item.get("job_pounds") or "").strip():
            item["job_pounds"] = f"{job_price:.2f}"

        if not str(item.get("miles_pounds") or "").strip():
            miles_val = _parse_miles(item.get("miles"))
            if miles_val > mileage_included and mileage_charge:
                extra = math.ceil(miles_val - mileage_included)
                item["miles_pounds"] = f"{extra * mileage_charge:.2f}"
            else:
                item["miles_pounds"] = "0.00"

        if not str(item.get("total") or "").strip():
            wait = float(item.get("wait_pounds") or 0)
            miles_p = float(item.get("miles_pounds") or 0)
            job_p = float(item.get("job_pounds") or 0)
            item["total"] = f"{wait + miles_p + job_p:.2f}"


# ---------------------------------------------------------------------------
# Calculated-value resolver (used by summary mapping)
# ---------------------------------------------------------------------------

def _get_calculated_value(invoice_data: dict, item: dict, index: int, field_id: str):
    """Get value for a calculated/synthetic field from line item or invoice data."""
    _ITEM_FIELD_MAP = {
        "_date": "date", "_our_ref": "our_ref", "_client_ref": "client_ref",
        "_mob": "mob", "_miles": "miles", "_wait_pounds": "wait_pounds",
        "_miles_pounds": "miles_pounds", "_job_pounds": "job_pounds",
        "_line_total": "total", "_wait_notes": "wait_notes",
        "_from_location": "from_location", "_to_location": "to_location",
        "_status": "status", "_directions": "directions",
        "_contract_hospital": "contract_hospital", "_booked_by": "booked_by",
        "_nhs_number": "nhs_number",
    }
    if field_id in _ITEM_FIELD_MAP:
        return str(item.get(_ITEM_FIELD_MAP[field_id]) or "").strip()

    patient = invoice_data.get("patient") or {}
    inv = invoice_data.get("invoice") or {}
    fin = invoice_data.get("financial") or {}
    _INVOICE_FIELD_MAP = {
        "_client_name": ("patient", "name"), "_client_address": ("patient", "address"),
        "_client_postcode": ("patient", "postcode"),
        "_invoice_number": ("invoice", "number"), "_invoice_date": ("invoice", "date"),
        "_subtotal": ("financial", "subtotal"), "_vat_amount": ("financial", "vat_amount"),
        "_invoice_total": ("financial", "total"),
        "_account_ref": ("invoice", "account_ref"), "_ref": ("invoice", "ref"),
        "_po_number": ("invoice", "po_number"), "_payment_terms": ("invoice", "payment_terms"),
        "_period": ("invoice", "period"),
    }
    if field_id in _INVOICE_FIELD_MAP:
        section, key = _INVOICE_FIELD_MAP[field_id]
        source = {"patient": patient, "invoice": inv, "financial": fin}.get(section, {})
        return str(source.get(key) or "").strip()
    return ""


# ---------------------------------------------------------------------------
# Summary-row builder
# ---------------------------------------------------------------------------

CHARGE_COLUMN_MAP = {
    "fixed charge":          "job_pounds",
    "mileage charge":        "miles_pounds",
    "waiting time charge":   "wait_pounds",
    "total charge":          "total",
}


def build_summary_rows_from_line_items(
    invoice_data: dict,
    source_df: pd.DataFrame,
    summary_columns: list,
    mapping: dict,
) -> list:
    """Build summary sheet rows from invoice line items plus source CSV.

    Mapped columns pull from the source CSV.  Charge columns (Fixed Charge,
    Mileage Charge, Waiting Time Charge, Total Charge) are always written
    from the invoice item's UI-calculated values, overriding any mapping.
    """
    items = (invoice_data.get("invoice") or {}).get("items") or []
    if not items:
        return []

    charge_indices = {}
    for col_idx, col_name in enumerate(summary_columns):
        item_key = CHARGE_COLUMN_MAP.get(col_name.strip().lower())
        if item_key:
            charge_indices[col_idx] = item_key

    rows = []
    for i, item in enumerate(items):
        src_idx = item.get("_source_row_index", i)
        source_row = source_df.iloc[src_idx] if src_idx < len(source_df) else None
        row = []
        for col_idx, sum_col in enumerate(summary_columns):
            if col_idx in charge_indices:
                val = str(item.get(charge_indices[col_idx]) or "").strip()
                row.append(val)
                continue
            src_or_calc = mapping.get(sum_col)
            if not src_or_calc:
                row.append("")
                continue
            if isinstance(src_or_calc, str) and src_or_calc.startswith("_"):
                row.append(_get_calculated_value(invoice_data, item, i, src_or_calc))
                continue
            if source_row is not None and src_or_calc in source_df.columns:
                val = source_row.get(src_or_calc)
                row.append("" if pd.isna(val) else str(val).strip())
            else:
                row.append("")
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# ZIP builder (single invoice + summary)
# ---------------------------------------------------------------------------

def try_build_summary_zip(
    invoice_data: dict, session_id: str, temp_dir: str, html_file: str,
) -> Optional[str]:
    """If summary template + mapping + source CSV all exist, build a ZIP with
    the invoice HTML and a filled summary CSV.  Returns the ZIP path, or None."""
    template_path = os.path.join(temp_dir, "summary_template.csv")
    mapping_path = os.path.join(temp_dir, "summary_mapping.json")
    source_csv_path = os.path.join(temp_dir, f"{session_id}_source.csv")

    if not (os.path.isfile(template_path) and os.path.isfile(mapping_path) and os.path.isfile(source_csv_path)):
        return None

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    summary_columns = list(pd.read_csv(template_path, nrows=0).columns)
    source_df = pd.read_csv(source_csv_path)

    rows = build_summary_rows_from_line_items(invoice_data, source_df, summary_columns, mapping)
    if not rows:
        return None

    out_df = pd.DataFrame(rows, columns=summary_columns)
    summary_csv_path = os.path.join(temp_dir, f"summary_single_{session_id}.csv")
    out_df.to_csv(summary_csv_path, index=False, encoding="utf-8")

    src_fn_path = os.path.join(temp_dir, f"{session_id}_source_filename.txt")
    if os.path.isfile(src_fn_path):
        with open(src_fn_path, "r", encoding="utf-8") as fn:
            invoice_stem = Path(fn.read().strip()).stem
    else:
        invoice_stem = Path(html_file).stem

    zip_path = os.path.join(temp_dir, f"invoice_and_summary_{session_id}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(html_file, Path(html_file).name)
        zipf.write(summary_csv_path, f"{invoice_stem}_backing_data.csv")
    return zip_path


# ---------------------------------------------------------------------------
# Merged summary builder (preserves user edits across recalculations)
# ---------------------------------------------------------------------------

def build_merged_summary(
    temp_dir: str, session_id: str, invoice_data: dict,
) -> Optional[tuple[list, list, list]]:
    """Build summary rows from the current invoice data, then overlay any cells
    that the user has previously manually edited and saved.

    Uses per-invoice template and mapping: summary_template_{session_id}.csv,
    summary_mapping_{session_id}.json.

    Returns (columns, rows, edited_cells) or None when no template/mapping.
    """
    template_path = os.path.join(temp_dir, f"summary_template_{session_id}.csv")
    mapping_path = os.path.join(temp_dir, f"summary_mapping_{session_id}.json")
    source_csv_path = os.path.join(temp_dir, f"{session_id}_source.csv")

    if not os.path.isfile(template_path) or not os.path.isfile(mapping_path):
        return None

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    template_df = pd.read_csv(template_path)
    summary_columns = list(template_df.columns)
    source_df = pd.read_csv(source_csv_path) if os.path.isfile(source_csv_path) else pd.DataFrame()

    ensure_line_item_charges(invoice_data)
    fresh_rows = build_summary_rows_from_line_items(
        invoice_data, source_df, summary_columns, mapping
    )

    saved_csv_path = os.path.join(temp_dir, f"summary_single_{session_id}.csv")
    edits_mask_path = os.path.join(temp_dir, f"summary_edits_{session_id}.json")
    edited_cells: list = []

    if os.path.isfile(saved_csv_path) and os.path.isfile(edits_mask_path):
        try:
            saved_df = pd.read_csv(saved_csv_path, dtype=str).fillna("")
            saved_rows = saved_df.values.tolist()
            with open(edits_mask_path, "r", encoding="utf-8") as f:
                mask_data = json.load(f)
            saved_edits = mask_data.get("edited_cells", [])

            surviving_edits = []
            for rc in saved_edits:
                r, c = rc[0], rc[1]
                if r < len(fresh_rows) and r < len(saved_rows) and c < len(summary_columns):
                    fresh_rows[r][c] = saved_rows[r][c]
                    surviving_edits.append([r, c])
            edited_cells = surviving_edits
        except Exception:
            logger.debug("Could not overlay saved summary edits", exc_info=True)

    return summary_columns, fresh_rows, edited_cells


# ---------------------------------------------------------------------------
# Calculated fields exposed to the frontend
# ---------------------------------------------------------------------------

SUMMARY_CALCULATED_FIELDS = [
    {"id": "_date", "label": "Date (calculated)"},
    {"id": "_our_ref", "label": "Our Ref (calculated)"},
    {"id": "_client_ref", "label": "Client Ref (calculated)"},
    {"id": "_mob", "label": "MOB (calculated)"},
    {"id": "_miles", "label": "Miles (calculated)"},
    {"id": "_wait_pounds", "label": "Wait £ (calculated)"},
    {"id": "_miles_pounds", "label": "Miles £ (calculated)"},
    {"id": "_job_pounds", "label": "Job £ (calculated)"},
    {"id": "_line_total", "label": "Line Total (calculated)"},
    {"id": "_wait_notes", "label": "Wait notes (calculated)"},
    {"id": "_from_location", "label": "From (calculated)"},
    {"id": "_to_location", "label": "To (calculated)"},
    {"id": "_client_name", "label": "Client Name (calculated)"},
    {"id": "_client_address", "label": "Client Address (calculated)"},
    {"id": "_client_postcode", "label": "Client Postcode (calculated)"},
    {"id": "_invoice_number", "label": "Invoice Number (calculated)"},
    {"id": "_invoice_date", "label": "Invoice Date (calculated)"},
    {"id": "_subtotal", "label": "Subtotal (calculated)"},
    {"id": "_vat_amount", "label": "VAT (calculated)"},
    {"id": "_invoice_total", "label": "Invoice Total (calculated)"},
]
