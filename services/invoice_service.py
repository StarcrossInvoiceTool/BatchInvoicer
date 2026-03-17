"""Invoice generation, HTML parsing, and serialisation helpers."""

import base64
import pickle
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

import config

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

DATE_FORMATS = [
    '%Y-%m-%d',
    '%Y/%m/%d',
    '%d/%m/%Y',
    '%d-%m-%Y',
    '%m/%d/%Y',
    '%m-%d-%Y',
    '%d %b %Y',
    '%d %B %Y',
    '%Y-%m-%d %H:%M:%S',
    '%Y/%m/%d %H:%M:%S',
]


def _parse_date(value) -> Optional[datetime]:
    """Try to coerce *value* into a datetime, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, 'year'):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _ordinal_suffix(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')


def format_date_word_format(date_value):
    """Format date to word format like '15th January 2026'."""
    if not date_value:
        return ''
    dt = _parse_date(date_value)
    if dt is None:
        return str(date_value)
    suffix = _ordinal_suffix(dt.day)
    return f"{dt.day}{suffix} {dt.strftime('%B')} {dt.year}"


def format_date_dd_mm_yyyy(date_value):
    """Format date to dd/mm/yyyy format."""
    if not date_value:
        return ''
    dt = _parse_date(date_value)
    if dt is None:
        return str(date_value)
    return dt.strftime('%d/%m/%Y')


def format_currency(value):
    """Format number as currency with commas and 2 decimal places (e.g., 1,234.56)."""
    if not value:
        return ''
    try:
        num = float(str(value).replace(',', ''))
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        return str(value)


# ---------------------------------------------------------------------------
# Financial normalisation
# ---------------------------------------------------------------------------

def _parse_money(value) -> Optional[float]:
    """Parse common money-ish inputs ('1,234.50', '£12.00', '') into float."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.lower() in ("nan", "none", "null"):
        return None
    s = s.replace("£", "").replace(",", "").strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _coerce_money_str(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _normalize_financial_totals(invoice_data: dict) -> None:
    """Ensure financial totals are VAT-consistent for rendering."""
    fin = invoice_data.get("financial")
    if not isinstance(fin, dict):
        return

    subtotal = _parse_money(fin.get("subtotal"))
    if subtotal is None:
        return

    vat_pct = _parse_money(fin.get("vat_percentage"))
    vat_pct = vat_pct or 0.0

    vat_amount = _parse_money(fin.get("vat_amount"))
    if vat_amount is None and vat_pct:
        vat_amount = round(subtotal * (vat_pct / 100.0), 2)
        fin["vat_amount"] = _coerce_money_str(vat_amount)

    expected_total = round(subtotal + (vat_amount or 0.0), 2)
    current_total = _parse_money(fin.get("total"))

    if current_total is None:
        fin["total"] = _coerce_money_str(expected_total)
        return

    if (vat_amount or 0.0) > 0.0:
        if abs(current_total - subtotal) < 0.01 and abs(current_total - expected_total) > 0.01:
            fin["total"] = _coerce_money_str(expected_total)


# ---------------------------------------------------------------------------
# Invoice HTML generation
# ---------------------------------------------------------------------------

def _build_jinja_env():
    """Create a Jinja2 Environment with invoice-specific filters."""
    templates_dir = config.BASE_DIR / config.TEMPLATES_DIR
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    env.filters['format_date'] = format_date_word_format
    env.filters['format_date_numeric'] = format_date_dd_mm_yyyy
    env.filters['format_currency'] = format_currency
    return env


def generate_invoice_html(
    invoice_data_path: str, template_name: str = None, embed_image: bool = True,
) -> str:
    """Generate HTML invoice from invoice data pickle file."""
    with open(invoice_data_path, 'rb') as f:
        invoice_data = pickle.load(f)

    _normalize_financial_totals(invoice_data)

    if template_name is None:
        style = invoice_data.get('style', config.DEFAULT_INVOICE_STYLE)
        template_name = (
            config.INVOICE_TEMPLATE_STYLE2 if style == 'style2'
            else config.INVOICE_TEMPLATE_STYLE1
        )

    env = _build_jinja_env()
    template = env.get_template(template_name)
    rendered_html = template.render(data=invoice_data)

    templates_img = config.BASE_DIR / config.TEMPLATES_DIR / config.LOGO_FILENAME
    static_img = config.BASE_DIR / config.STATIC_DIR / config.LOGO_FILENAME
    paid_stamp_img = config.BASE_DIR / config.STATIC_DIR / config.PAID_STAMP_FILENAME

    if embed_image:
        img_path = static_img if static_img.exists() else (templates_img if templates_img.exists() else None)
        if img_path:
            with open(img_path, 'rb') as img_file:
                img_b64 = f"data:image/jpeg;base64,{base64.b64encode(img_file.read()).decode('utf-8')}"
                rendered_html = rendered_html.replace(f'/static/{config.LOGO_FILENAME}', img_b64)

        if invoice_data.get('paid', False) and paid_stamp_img.exists():
            with open(paid_stamp_img, 'rb') as img_file:
                stamp_b64 = f"data:image/png;base64,{base64.b64encode(img_file.read()).decode('utf-8')}"
                rendered_html = rendered_html.replace(f'/static/{config.PAID_STAMP_FILENAME}', stamp_b64)

    invoice_html_dir = config.BASE_DIR / config.INVOICE_HTML_DIR
    invoice_html_dir.mkdir(exist_ok=True)

    session_id = Path(invoice_data_path).stem.replace('_invoice_data', '')
    batch_dir = Path(invoice_data_path).parent
    source_fn_path = batch_dir / f"{session_id}_source_filename.txt"
    if source_fn_path.exists():
        try:
            with open(source_fn_path, 'r', encoding='utf-8') as f:
                source_filename = f.read().strip()
            stem = Path(source_filename).stem
            output_filename = f"{stem}_invoice.html"
        except Exception:
            output_filename = f"{session_id}_invoice.html"
    else:
        output_filename = f"{session_id}_invoice.html"
    output_file = invoice_html_dir / output_filename

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(rendered_html)

    return str(output_file)


# ---------------------------------------------------------------------------
# HTML invoice parser (sub-functions)
# ---------------------------------------------------------------------------

def _extract_patient_info(page_content) -> dict:
    """Extract patient name, address, and postcode from the left side of the invoice."""
    info = {'name': '', 'address': '', 'postcode': ''}
    if not page_content:
        return info
    patient_div = page_content.find('div', class_='w-1/2')
    if not patient_div:
        return info
    paragraphs = patient_div.find_all('p', class_='text-gray-700')
    if len(paragraphs) >= 1:
        info['name'] = paragraphs[0].get_text(strip=True)
    if len(paragraphs) >= 2:
        info['address'] = paragraphs[1].get_text(strip=True)
    if len(paragraphs) >= 3:
        info['postcode'] = paragraphs[2].get_text(strip=True)
    return info


def _extract_invoice_header(page_content) -> dict:
    """Extract header fields (number, date, account_ref, etc.) from the right-side grid."""
    fields = {
        'number': '', 'date': '', 'account_ref': '', 'ref': '',
        'po_number': '', 'payment_terms': '', 'period': '',
    }
    if not page_content:
        return fields

    right_div = page_content.find('div', class_='w-1/2', string=re.compile('text-right'))
    if not right_div:
        right_divs = page_content.find_all('div', class_='w-1/2')
        right_div = right_divs[1] if len(right_divs) >= 2 else None
    if not right_div:
        return fields

    grid = right_div.find('div', class_='grid')
    if not grid:
        return fields

    LABEL_KEY_MAP = {
        'Invoice Number': 'number',
        'Invoice Date': 'date',
        'Account Reference': 'account_ref',
        'Reference:': 'ref',
        'PO Number': 'po_number',
        'Payment Terms': 'payment_terms',
        'Period:': 'period',
    }
    spans = grid.find_all('span')
    for i in range(0, len(spans) - 1, 2):
        label = spans[i].get_text(strip=True)
        value = spans[i + 1].get_text(strip=True) if i + 1 < len(spans) else ''
        for key_prefix, field_name in LABEL_KEY_MAP.items():
            if key_prefix in label or label == key_prefix:
                fields[field_name] = value
                break
    return fields


def _extract_financial_info(page_content) -> dict:
    """Extract net, discount, subtotal, VAT and total from the financial section."""
    result = {
        'net': '', 'net_label': 'net',
        'discount': '', 'discount_label': 'discount',
        'subtotal': '', 'subtotal_label': 'Invoice subtotal',
        'vat_amount': '', 'vat_label': 'VAT 20%',
        'total': '', 'total_label': 'TOTAL DUE',
    }
    if not page_content:
        return result

    for financial_div in page_content.find_all('div', class_='flex'):
        if 'justify-end' not in financial_div.get('class', []):
            continue
        for item in financial_div.find_all('div', class_='flex'):
            if 'justify-between' not in item.get('class', []):
                continue
            spans = item.find_all('span')
            if len(spans) < 2:
                continue
            label = spans[0].get_text(strip=True)
            value = spans[1].get_text(strip=True).replace('£', '').strip()
            ll = label.lower()
            if 'net' in ll and not result['net']:
                result['net'], result['net_label'] = value, label
            elif 'discount' in ll and not result['discount']:
                result['discount'], result['discount_label'] = value, label
            elif 'subtotal' in ll and not result['subtotal']:
                result['subtotal'], result['subtotal_label'] = value, label
            elif 'vat' in ll and not result['vat_amount']:
                result['vat_amount'], result['vat_label'] = value, label
            elif 'total' in ll and 'due' in ll:
                result['total'], result['total_label'] = value, label
    return result


def _span_text(span, strip_pound=False) -> str:
    """Safely extract text from a BeautifulSoup span (or None)."""
    if span is None:
        return ''
    text = span.get_text(strip=True)
    if strip_pound:
        text = text.replace('£', '').strip()
    return text


_COL_START_MAP = {
    'col-start-1': 'status', 'col-start-3': 'directions', 'col-start-5': 'mob',
    'col-start-7': 'wait_pounds', 'col-start-9': 'wait_notes',
    'col-start-12': 'miles', 'col-start-14': 'charged',
    'col-start-16': 'miles_pounds', 'col-start-18': 'job_pounds',
    'col-start-20': 'total',
}


def _extract_line_items(soup) -> list[dict]:
    """Extract invoice line items from data-grid elements."""
    grids_to_process = []

    for div in soup.find_all('div', class_='invoice-line-item'):
        grid = div.find('div', class_='data-grid')
        if grid:
            grids_to_process.append(grid)

    if not grids_to_process:
        all_data_grids = soup.find_all('div', class_='data-grid')
        header_grid = None
        for grid in all_data_grids:
            if grid.find_all('span', class_='font-bold'):
                header_grid = grid
                break
        for grid in all_data_grids:
            if grid != header_grid and len(grid.find_all('span')) >= 15:
                grids_to_process.append(grid)

    items = []
    for grid in grids_to_process:
        span_map: dict = {}
        first_row_list: list = []

        for span in grid.find_all('span'):
            classes = span.get('class', [])
            class_str = ' '.join(str(c) for c in classes) if isinstance(classes, list) else str(classes)
            class_list = classes if isinstance(classes, list) else ([classes] if classes else [])

            matched = False
            for css_class, key in _COL_START_MAP.items():
                if css_class in class_str or css_class in class_list:
                    span_map[key] = span
                    matched = True
                    break
            if not matched:
                has_col_span = 'col-span' in class_str or any('col-span' in str(c) for c in class_list)
                has_col_start = 'col-start' in class_str or any('col-start' in str(c) for c in class_list)
                if has_col_span and not has_col_start:
                    first_row_list.append(span)

        booked_by_idx, from_idx, to_idx = 6, 7, 8
        if len(first_row_list) > 5:
            span_5_classes = first_row_list[5].get('class', [])
            span_5_text = first_row_list[5].get_text(strip=True)
            if not ('col-span-4' in ' '.join(str(c) for c in span_5_classes) and not span_5_text):
                booked_by_idx, from_idx, to_idx = 5, 6, 7
        elif len(first_row_list) == 5:
            booked_by_idx, from_idx, to_idx = 5, 6, 7

        def _fr(idx):
            return first_row_list[idx].get_text(strip=True) if len(first_row_list) > idx else ''

        item = {
            'date': _fr(0), 'our_ref': _fr(1), 'client_ref': _fr(2),
            'nhs_number': _fr(3), 'contract_hospital': _fr(4),
            'booked_by': _fr(booked_by_idx), 'from_location': _fr(from_idx),
            'to_location': _fr(to_idx),
            'status': _span_text(span_map.get('status')),
            'directions': _span_text(span_map.get('directions')),
            'mob': _span_text(span_map.get('mob')),
            'wait_pounds': _span_text(span_map.get('wait_pounds'), strip_pound=True),
            'wait_notes': _span_text(span_map.get('wait_notes')),
            'miles': _span_text(span_map.get('miles')),
            'charged': _span_text(span_map.get('charged')),
            'miles_pounds': _span_text(span_map.get('miles_pounds'), strip_pound=True),
            'job_pounds': _span_text(span_map.get('job_pounds'), strip_pound=True),
            'total': _span_text(span_map.get('total'), strip_pound=True),
        }
        if item['date'] or item['our_ref']:
            items.append(item)
    return items


def parse_html_invoice(html_content: str) -> dict:
    """Parse HTML invoice and extract invoice data structure."""
    soup = BeautifulSoup(html_content, 'html.parser')
    page_content = soup.find('div', class_='page-content')

    patient = _extract_patient_info(page_content)
    header = _extract_invoice_header(page_content)
    financial = _extract_financial_info(page_content)
    financial['vat_percentage'] = config.DEFAULT_VAT_PERCENTAGE
    line_items = _extract_line_items(soup)

    return {
        'patient': patient,
        'invoice': {
            'number': header['number'],
            'date': header['date'],
            'account_ref': header['account_ref'],
            'ref': header['ref'],
            'po_number': header['po_number'],
            'payment_terms': header['payment_terms'],
            'period': header['period'],
            'items': line_items,
        },
        'financial': financial,
        'bank': {
            'name': config.DEFAULT_BANK_NAME,
            'account_name': config.DEFAULT_ACCOUNT_NAME,
            'account_number': config.DEFAULT_ACCOUNT_NUMBER,
            'sort_code': config.DEFAULT_SORT_CODE,
        },
        'paid': False,
        'style': config.DEFAULT_INVOICE_STYLE,
        'item_name': '',
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def serialize_invoice_data(invoice_data):
    """Convert invoice_data to JSON-serializable format.

    Handles pandas objects, datetime objects, numpy arrays, and other
    non-serializable types.
    """
    def convert_value(value):
        if value is None:
            return None
        if isinstance(value, (pd.Series, pd.DataFrame)):
            return value.tolist() if hasattr(value, 'tolist') else str(value)
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return value.isoformat() if hasattr(value, 'isoformat') else str(value)
        if isinstance(value, dict):
            return {k: convert_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert_value(item) for item in value]
        try:
            if isinstance(value, (int, float, complex)):
                if pd.isna(value) or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
                    return None
        except (ValueError, TypeError):
            pass
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    return convert_value(invoice_data)
