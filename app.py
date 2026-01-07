from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import os
import zipfile
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import pickle
from typing import Optional
import json

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system environment variables

from xslx_to_csv import xlsx_to_csv
from csv_cleaner import csv_to_dataframe
from DataScraper import transform_dataframe_to_invoice_data
from divider import split_csv_by_budget_code
from jinja2 import Environment, FileSystemLoader
from auth import verify_user, create_session_token, verify_session_token, SESSION_COOKIE_NAME
from authAzure import azure_scheme
from bs4 import BeautifulSoup
import re
from datetime import datetime
import time
import traceback

app = FastAPI(title="Batch Invoicer", description="Convert XLSX to CSV and generate invoices")

# In-memory cache for OAuth state (as backup to session storage)
# Key: state value, Value: timestamp when created
_oauth_state_cache = {}

def _cleanup_oauth_cache():
    """Remove OAuth states older than 10 minutes"""
    current_time = time.time()
    expired_states = [
        state for state, timestamp in _oauth_state_cache.items()
        if current_time - timestamp > 600  # 10 minutes
    ]
    for state in expired_states:
        _oauth_state_cache.pop(state, None)

def _store_oauth_state(state: str):
    """Store OAuth state in cache"""
    _cleanup_oauth_cache()
    _oauth_state_cache[state] = time.time()

def _verify_oauth_state(state: str) -> bool:
    """Verify OAuth state exists in cache"""
    _cleanup_oauth_cache()
    return state in _oauth_state_cache

def _remove_oauth_state(state: str):
    """Remove OAuth state from cache after use"""
    _oauth_state_cache.pop(state, None)

# Handle favicon requests to prevent 404 errors
@app.get("/favicon.ico")
async def favicon():
    """Handle favicon requests"""
    from fastapi.responses import Response
    return Response(status_code=204)  # No Content

# Add session middleware for OAuth state management
# Configure with same_site="lax" to ensure cookies work with OAuth redirects
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SECRET_KEY", "your-secret-key-change-this"),
    same_site="lax",
    https_only=False  # Set to True in production with HTTPS
)

def format_date_word_format(date_value):
    """Format date to word format like '15th January 2026'"""
    if not date_value:
        return ''
    
    def get_ordinal_suffix(day):
        """Get ordinal suffix for day (1st, 2nd, 3rd, 4th, etc.)"""
        if 10 <= day % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        return suffix
    
    # If it's already a string, try to parse it
    if isinstance(date_value, str):
        # Try various date formats
        date_formats = [
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
        
        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_value, fmt)
                day = dt.day
                month = dt.strftime('%B')  # Full month name
                year = dt.year
                suffix = get_ordinal_suffix(day)
                return f"{day}{suffix} {month} {year}"
            except ValueError:
                continue
        
        # If parsing fails, return original string
        return date_value
    
    # If it's a datetime object
    if isinstance(date_value, datetime):
        day = date_value.day
        month = date_value.strftime('%B')  # Full month name
        year = date_value.year
        suffix = get_ordinal_suffix(day)
        return f"{day}{suffix} {month} {year}"
    
    # If it's a date object
    if hasattr(date_value, 'strftime'):
        day = date_value.day
        month = date_value.strftime('%B')  # Full month name
        year = date_value.year
        suffix = get_ordinal_suffix(day)
        return f"{day}{suffix} {month} {year}"
    
    return str(date_value)


def format_currency(value):
    """Format number as currency with commas and 2 decimal places (e.g., 1,234.56)"""
    if not value:
        return ''
    
    try:
        # Convert to float if it's a string
        num = float(str(value).replace(',', ''))
        # Format with commas and 2 decimal places
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        # If conversion fails, return original value
        return str(value)

def format_date_dd_mm_yyyy(date_value):
    """Format date to dd/mm/yyyy format"""
    if not date_value:
        return ''
    
    # If it's already a string, try to parse it
    if isinstance(date_value, str):
        # Try various date formats
        date_formats = [
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
        
        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_value, fmt)
                return dt.strftime('%d/%m/%Y')
            except ValueError:
                continue
        
        # If parsing fails, return original string
        return date_value
    
    # If it's a datetime object
    if isinstance(date_value, datetime):
        return date_value.strftime('%d/%m/%Y')
    
    # If it's a date object
    if hasattr(date_value, 'strftime'):
        return date_value.strftime('%d/%m/%Y')
    
    return str(date_value)

# Create necessary directories
os.makedirs("uploads", exist_ok=True)
os.makedirs("invoice html", exist_ok=True)
os.makedirs("temp", exist_ok=True)
os.makedirs("static", exist_ok=True)  # Create static directory if it doesn't exist

# Mount static files and templates (only if static directory exists)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
# Configure templates with auto-reload disabled in production, but enabled for development
templates = Jinja2Templates(directory="templates", auto_reload=True)


# Azure SSO Authentication (optional - can be used for API routes)
async def get_azure_user(request: Request, token: Optional[str] = Depends(azure_scheme)) -> Optional[dict]:
    """Get current authenticated user from Azure AD token"""
    if token:
        # Token is validated by azure_scheme, extract user info
        # The token contains claims like 'preferred_username', 'name', 'email', etc.
        return token
    return None

# Session-based Authentication (for HTML routes)
async def get_current_user(request: Request) -> Optional[str]:
    """Get current authenticated user from session"""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None
    
    username = verify_session_token(session_token)
    return username


async def require_auth(request: Request, current_user: Optional[str] = Depends(get_current_user)):
    """Dependency that requires authentication - raises exception if not authenticated"""
    if not current_user:
        # For API routes, raise HTTPException with 401
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Authentication required")
        # For HTML routes, raise a custom exception that will be caught by the handler
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return current_user


# Exception handler for authentication redirects
@app.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    """Handle authentication redirects for HTML routes"""
    # If it's a 401 and not an API route, redirect to login
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and not request.url.path.startswith("/api/"):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    # For API routes with 401, return JSON
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    # For other HTTPExceptions, use default behavior
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


def generate_invoice_html(invoice_data_path: str, template_name: str = None, embed_image: bool = True) -> str:
    """Generate HTML invoice from invoice data pickle file"""
    import base64
    
    # Load invoice data
    with open(invoice_data_path, 'rb') as f:
        invoice_data = pickle.load(f)
    
    # Determine template based on style if not explicitly provided
    if template_name is None:
        style = invoice_data.get('style', 'style1')
        if style == 'style2':
            template_name = 'Invoice 2 - Style 2.html'
        else:
            template_name = 'Invoice 2.html'
    
    # Set up Jinja2 environment
    templates_dir = Path(__file__).parent / 'templates'
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    env.filters['format_date'] = format_date_word_format  # Invoice header date in word format
    env.filters['format_date_numeric'] = format_date_dd_mm_yyyy  # Line item dates in numeric format
    env.filters['format_currency'] = format_currency  # Format numbers with commas and 2 decimal places
    template = env.get_template(template_name)
    
    # Render the template
    rendered_html = template.render(data=invoice_data)
    
    # Fix image path for standalone HTML
    templates_img = Path(__file__).parent / 'templates' / 'bears-pts logo.jpg'
    static_img = Path(__file__).parent / 'static' / 'bears-pts logo.jpg'
    paid_stamp_img = Path(__file__).parent / 'static' / 'PAID STAMP.png'
    
    if embed_image:
        # Embed image as base64 for standalone HTML files
        img_path = None
        if static_img.exists():
            img_path = static_img
        elif templates_img.exists():
            img_path = templates_img
        
        if img_path:
            with open(img_path, 'rb') as img_file:
                img_data = base64.b64encode(img_file.read()).decode('utf-8')
                img_base64 = f"data:image/jpeg;base64,{img_data}"
                rendered_html = rendered_html.replace('/static/bears-pts logo.jpg', img_base64)
        
        # Embed PAID STAMP if invoice is marked as paid
        if invoice_data.get('paid', False) and paid_stamp_img.exists():
            with open(paid_stamp_img, 'rb') as img_file:
                img_data = base64.b64encode(img_file.read()).decode('utf-8')
                img_base64 = f"data:image/png;base64,{img_data}"
                rendered_html = rendered_html.replace('/static/PAID STAMP.png', img_base64)
    else:
        # For preview, keep the static path (FastAPI will serve it)
        pass
    
    # Save to invoice html folder
    invoice_html_dir = Path(__file__).parent / 'invoice html'
    invoice_html_dir.mkdir(exist_ok=True)
    
    output_filename = Path(invoice_data_path).stem.replace('_invoice_data', '') + '_invoice.html'
    output_file = invoice_html_dir / output_filename
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
    
    return str(output_file)


def parse_html_invoice(html_content: str) -> dict:
    """Parse HTML invoice and extract invoice data structure"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract patient information
    patient_name = ''
    patient_address = ''
    patient_postcode = ''
    
    # Find patient info in the first page (left side)
    page_content = soup.find('div', class_='page-content')
    if page_content:
        patient_div = page_content.find('div', class_='w-1/2')
        if patient_div:
            paragraphs = patient_div.find_all('p', class_='text-gray-700')
            if len(paragraphs) >= 1:
                patient_name = paragraphs[0].get_text(strip=True)
            if len(paragraphs) >= 2:
                patient_address = paragraphs[1].get_text(strip=True)
            if len(paragraphs) >= 3:
                patient_postcode = paragraphs[2].get_text(strip=True)
    
    # Extract invoice header information
    invoice_number = ''
    invoice_date = ''
    account_ref = ''
    ref = ''
    po_number = ''
    payment_terms = ''
    period = ''
    
    # Find invoice info in the right side
    right_div = page_content.find('div', class_='w-1/2', string=re.compile('text-right'))
    if not right_div:
        right_divs = page_content.find_all('div', class_='w-1/2')
        if len(right_divs) >= 2:
            right_div = right_divs[1]
    
    if right_div:
        grid = right_div.find('div', class_='grid')
        if grid:
            spans = grid.find_all('span')
            for i, span in enumerate(spans):
                text = span.get_text(strip=True)
                if 'Invoice Number:' in text or (i > 0 and spans[i-1].get_text(strip=True) == 'Invoice Number:'):
                    if 'Invoice Number:' not in text:
                        invoice_number = text
                elif 'Invoice Date:' in text or (i > 0 and spans[i-1].get_text(strip=True) == 'Invoice Date:'):
                    if 'Invoice Date:' not in text:
                        invoice_date = text
                elif 'Account Reference:' in text or (i > 0 and spans[i-1].get_text(strip=True) == 'Account Reference:'):
                    if 'Account Reference:' not in text:
                        account_ref = text
                elif text == 'Reference:' or (i > 0 and spans[i-1].get_text(strip=True) == 'Reference:'):
                    if text != 'Reference:':
                        ref = text
                elif 'PO Number:' in text or (i > 0 and spans[i-1].get_text(strip=True) == 'PO Number:'):
                    if 'PO Number:' not in text:
                        po_number = text
                elif 'Payment Terms:' in text or (i > 0 and spans[i-1].get_text(strip=True) == 'Payment Terms:'):
                    if 'Payment Terms:' not in text:
                        payment_terms = text
                elif text == 'Period:' or (i > 0 and spans[i-1].get_text(strip=True) == 'Period:'):
                    if text != 'Period:':
                        period = text
    
    # Better extraction using label-value pairs
    if right_div:
        grid = right_div.find('div', class_='grid')
        if grid:
            spans = grid.find_all('span')
            for i in range(0, len(spans) - 1, 2):
                label = spans[i].get_text(strip=True)
                value = spans[i + 1].get_text(strip=True) if i + 1 < len(spans) else ''
                
                if 'Invoice Number' in label:
                    invoice_number = value
                elif 'Invoice Date' in label:
                    invoice_date = value
                elif 'Account Reference' in label:
                    account_ref = value
                elif label == 'Reference:':
                    ref = value
                elif 'PO Number' in label:
                    po_number = value
                elif 'Payment Terms' in label:
                    payment_terms = value
                elif label == 'Period:':
                    period = value
    
    # Extract financial information
    net = ''
    net_label = 'net'
    discount = ''
    discount_label = 'discount'
    subtotal = ''
    subtotal_label = 'Invoice subtotal'
    vat_amount = ''
    vat_label = 'VAT 20%'
    total = ''
    total_label = 'TOTAL DUE'
    
    # Find financial section - look for div with flex and justify-end classes
    financial_sections = page_content.find_all('div', class_='flex')
    for financial_div in financial_sections:
        if 'justify-end' in financial_div.get('class', []):
            financial_items = financial_div.find_all('div', class_='flex')
            for item in financial_items:
                if 'justify-between' in item.get('class', []):
                    spans = item.find_all('span')
                    if len(spans) >= 2:
                        label = spans[0].get_text(strip=True)
                        value = spans[1].get_text(strip=True)
                        
                        # Remove £ sign if present
                        value = value.replace('£', '').strip()
                        
                        if 'net' in label.lower() and not net:
                            net = value
                            net_label = label
                        elif 'discount' in label.lower() and not discount:
                            discount = value
                            discount_label = label
                        elif 'subtotal' in label.lower() and not subtotal:
                            subtotal = value
                            subtotal_label = label
                        elif 'vat' in label.lower() and not vat_amount:
                            vat_amount = value
                            vat_label = label
                        elif 'total' in label.lower() and 'due' in label.lower():
                            total = value
                            total_label = label
    
    # Extract line items - try multiple approaches
    invoice_items = []
    
    # Approach 1: Find invoice-line-item divs
    line_item_divs = soup.find_all('div', class_='invoice-line-item')
    grids_to_process = []
    
    for line_item_div in line_item_divs:
        grid = line_item_div.find('div', class_='data-grid')
        if grid:
            grids_to_process.append(grid)
    
    # Approach 2: If no invoice-line-item divs found, find data-grid divs directly
    if not grids_to_process:
        # Find all data-grid divs
        all_data_grids = soup.find_all('div', class_='data-grid')
        # Find the header grid (it has font-bold spans)
        header_grid = None
        for grid in all_data_grids:
            bold_spans = grid.find_all('span', class_='font-bold')
            if bold_spans:
                header_grid = grid
                break
        
        # Process all data-grids except the header
        for grid in all_data_grids:
            if grid != header_grid:
                spans = grid.find_all('span')
                # Line items should have many spans (at least 15-20)
                if len(spans) >= 15:
                    grids_to_process.append(grid)
    
    # Process each grid
    for grid in grids_to_process:
        # Get all spans in the grid
        all_spans = grid.find_all('span')
        
        # Build a dictionary to map spans by their CSS classes
        span_map = {}
        first_row_list = []
        
        for span in all_spans:
            classes = span.get('class', [])
            # Handle both list and string formats
            if isinstance(classes, list):
                class_str = ' '.join(str(c) for c in classes)
                class_list = classes
            else:
                class_str = str(classes)
                class_list = [classes] if classes else []
            
            # Check for col-start in both string and list formats
            has_col_start_1 = 'col-start-1' in class_str or 'col-start-1' in class_list
            has_col_start_3 = 'col-start-3' in class_str or 'col-start-3' in class_list
            has_col_start_5 = 'col-start-5' in class_str or 'col-start-5' in class_list
            has_col_start_7 = 'col-start-7' in class_str or 'col-start-7' in class_list
            has_col_start_9 = 'col-start-9' in class_str or 'col-start-9' in class_list
            has_col_start_12 = 'col-start-12' in class_str or 'col-start-12' in class_list
            has_col_start_14 = 'col-start-14' in class_str or 'col-start-14' in class_list
            has_col_start_16 = 'col-start-16' in class_str or 'col-start-16' in class_list
            has_col_start_18 = 'col-start-18' in class_str or 'col-start-18' in class_list
            has_col_start_20 = 'col-start-20' in class_str or 'col-start-20' in class_list
            has_col_span = 'col-span' in class_str or any('col-span' in str(c) for c in class_list)
            has_col_start = 'col-start' in class_str or any('col-start' in str(c) for c in class_list)
            
            # Map second row items by col-start
            if has_col_start_1:
                span_map['status'] = span
            elif has_col_start_3:
                span_map['directions'] = span
            elif has_col_start_5:
                span_map['mob'] = span
            elif has_col_start_7:
                span_map['wait_pounds'] = span
            elif has_col_start_9:
                span_map['wait_notes'] = span
            elif has_col_start_12:
                span_map['miles'] = span
            elif has_col_start_14:
                span_map['charged'] = span
            elif has_col_start_16:
                span_map['miles_pounds'] = span
            elif has_col_start_18:
                span_map['job_pounds'] = span
            elif has_col_start_20:
                span_map['total'] = span
            elif has_col_span and not has_col_start:
                # First row items (no col-start) - add to list in order
                first_row_list.append(span)
        
        # Extract first row data
        # Expected order: date (0), our_ref (1), client_ref (2), nhs_number (3), contract_hospital (4), empty (5), booked_by (6), from_location (7), to_location (8)
        # Handle the empty span - it might be present but empty, or missing entirely
        booked_by_idx = 6
        from_location_idx = 7
        to_location_idx = 8
        
        # Check if we have the empty span at index 5
        if len(first_row_list) > 5:
            # Check if index 5 is the empty span (col-span-4 with no content)
            span_5_classes = first_row_list[5].get('class', [])
            span_5_text = first_row_list[5].get_text(strip=True)
            if 'col-span-4' in ' '.join(str(c) for c in span_5_classes) and not span_5_text:
                # It's the empty span, use original indices
                pass
            else:
                # It's not empty, so the empty span is missing - adjust indices
                booked_by_idx = 5
                from_location_idx = 6
                to_location_idx = 7
        elif len(first_row_list) == 5:
            # Only 5 spans, empty span is missing
            booked_by_idx = 5
            from_location_idx = 6
            to_location_idx = 7
        
        item = {
            'date': first_row_list[0].get_text(strip=True) if len(first_row_list) > 0 else '',
            'our_ref': first_row_list[1].get_text(strip=True) if len(first_row_list) > 1 else '',
            'client_ref': first_row_list[2].get_text(strip=True) if len(first_row_list) > 2 else '',
            'nhs_number': first_row_list[3].get_text(strip=True) if len(first_row_list) > 3 else '',
            'contract_hospital': first_row_list[4].get_text(strip=True) if len(first_row_list) > 4 else '',
            'booked_by': first_row_list[booked_by_idx].get_text(strip=True) if len(first_row_list) > booked_by_idx else '',
            'from_location': first_row_list[from_location_idx].get_text(strip=True) if len(first_row_list) > from_location_idx else '',
            'to_location': first_row_list[to_location_idx].get_text(strip=True) if len(first_row_list) > to_location_idx else '',
            'status': span_map.get('status').get_text(strip=True) if span_map.get('status') is not None else '',
            'directions': span_map.get('directions').get_text(strip=True) if span_map.get('directions') is not None else '',
            'mob': span_map.get('mob').get_text(strip=True) if span_map.get('mob') is not None else '',
            'wait_pounds': span_map.get('wait_pounds').get_text(strip=True).replace('£', '').strip() if span_map.get('wait_pounds') is not None else '',
            'wait_notes': span_map.get('wait_notes').get_text(strip=True) if span_map.get('wait_notes') is not None else '',
            'miles': span_map.get('miles').get_text(strip=True) if span_map.get('miles') is not None else '',
            'charged': span_map.get('charged').get_text(strip=True) if span_map.get('charged') is not None else '',
            'miles_pounds': span_map.get('miles_pounds').get_text(strip=True).replace('£', '').strip() if span_map.get('miles_pounds') is not None else '',
            'job_pounds': span_map.get('job_pounds').get_text(strip=True).replace('£', '').strip() if span_map.get('job_pounds') is not None else '',
            'total': span_map.get('total').get_text(strip=True).replace('£', '').strip() if span_map.get('total') is not None else ''
        }
        
        # Only add if date or our_ref is not empty
        if item['date'] or item['our_ref']:
            invoice_items.append(item)
    
    # Extract bank details (static, but included for completeness)
    bank_name = 'Lloyds Bank Plc'
    account_name = 'Starcross Trading Limited'
    account_number = '82082760'
    sort_code = '30-99-21'
    
    # Build invoice data structure
    invoice_data = {
        'patient': {
            'name': patient_name,
            'address': patient_address,
            'postcode': patient_postcode
        },
        'invoice': {
            'number': invoice_number,
            'date': invoice_date,
            'account_ref': account_ref,
            'ref': ref,
            'po_number': po_number,
            'payment_terms': payment_terms,
            'period': period,
            'items': invoice_items
        },
        'financial': {
            'net': net,
            'net_label': net_label,
            'discount': discount,
            'discount_label': discount_label,
            'subtotal': subtotal,
            'subtotal_label': subtotal_label,
            'vat_amount': vat_amount,
            'vat_label': vat_label,
            'vat_percentage': '20',  # Default VAT percentage, can be extracted from label if needed
            'total': total,
            'total_label': total_label
        },
        'bank': {
            'name': bank_name,
            'account_name': account_name,
            'account_number': account_number,
            'sort_code': sort_code
        },
        'paid': False,  # Default to False when parsing HTML (can be set via UI)
        'style': 'style1',  # Default to style1 when parsing HTML
        'item_name': ''  # Default to empty when parsing HTML
    }
    
    return invoice_data


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page - accessible without authentication"""
    # Redirect if already logged in
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        username = verify_session_token(session_token)
        if username:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    
    error = request.query_params.get("error")
    use_azure_sso_env = os.getenv("USE_AZURE_SSO", "false")
    use_azure_sso = use_azure_sso_env.lower() == "true"
    
    response = templates.TemplateResponse("login.html", {
        "request": request, 
        "error": error,
        "use_azure_sso": use_azure_sso
    })
    
    # Add cache-control headers to prevent browser caching during development
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    return response


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page - for troubleshooting purposes"""
    # Redirect if already logged in
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        username = verify_session_token(session_token)
        if username:
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    
    error = request.query_params.get("error")
    
    return templates.TemplateResponse("admin_login.html", {
        "request": request, 
        "error": error
    })


@app.post("/admin/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle admin login form submission"""
    if verify_user(username, password):
        # Create session token
        session_token = create_session_token(username)
        
        # Create response and set cookie
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=86400  # 24 hours
        )
        return response
    else:
        return RedirectResponse(url="/admin/login?error=invalid_credentials", status_code=status.HTTP_302_FOUND)


async def check_mailbox_access(access_token: str, mailbox_email: str) -> bool:
    """
    Check if the authenticated user has access to the specified mailbox.
    Uses Microsoft Graph API to check mailbox permissions.
    
    This checks if the user can:
    1. List user's mailboxes and check if target mailbox appears (most reliable for shared mailboxes)
    2. Access the mailbox inbox folder directly (FullAccess permission)
    3. Access mailbox settings (alternative check)
    
    Returns True if user has access, False otherwise.
    """
    from authAzure import GRAPH_API_ENDPOINT
    import httpx
    
    if not mailbox_email:
        # If no mailbox is configured, allow all users
        return True
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            print(f"[DEBUG] Checking mailbox access for: {mailbox_email}")
            
            # Method 1: NEW PRIMARY CHECK - List user's mailboxes and check if target mailbox appears
            # This is the most reliable method for shared mailboxes that the user has been granted access to
            # Shared mailboxes with FullAccess appear in the user's mailbox list
            print(f"[DEBUG] METHOD 1: Checking if mailbox appears in user's accessible mailboxes...")
            try:
                # Get the current user's info first to use their ID
                user_info_response = await client.get(
                    f"{GRAPH_API_ENDPOINT}/me",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                if user_info_response.status_code == 200:
                    user_info = user_info_response.json()
                    user_id = user_info.get("id") or user_info.get("userPrincipalName")
                    print(f"[DEBUG] Current user ID: {user_id}")
                    
                    # Try to get user's mailboxes - shared mailboxes they have access to should appear here
                    # Note: This endpoint lists mailboxes, but shared mailboxes might not always appear
                    # We'll use this as one check, but also try direct access
                    
                    # Alternative: Try to find the mailbox in user's mail folders
                    # Shared mailboxes with FullAccess can be accessed via /users/{mailbox}/mailFolders
                    pass  # We'll try direct access methods below
                else:
                    print(f"[DEBUG] Could not get user info: {user_info_response.status_code}")
            except Exception as e:
                print(f"[DEBUG] Error getting user info: {e}")
            
            # Method 2: PRIMARY CHECK - Try to access mailbox inbox folder directly
            # This is the most reliable check for FullAccess permission
            print(f"[DEBUG] METHOD 2: Attempting to access inbox folder directly...")
            inbox_response = await client.get(
                f"{GRAPH_API_ENDPOINT}/users/{mailbox_email}/mailFolders/inbox",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )
            
            if inbox_response.status_code == 200:
                print(f"[DEBUG] ✓ METHOD 2 PASSED: Successfully accessed inbox for {mailbox_email} - FullAccess confirmed")
                return True
            
            # Log the error for debugging
            inbox_error = ""
            try:
                inbox_error_body = inbox_response.json()
                inbox_error = f" - {inbox_error_body}"
                error_code = inbox_error_body.get("error", {}).get("code", "")
                error_message = inbox_error_body.get("error", {}).get("message", "")
                print(f"[DEBUG] METHOD 2 FAILED: Status {inbox_response.status_code}, Code: {error_code}, Message: {error_message}")
            except:
                inbox_error = f" - {inbox_response.text[:200]}"
                print(f"[DEBUG] METHOD 2 FAILED: Cannot access inbox for {mailbox_email}: Status {inbox_response.status_code}{inbox_error}")
            
            # Method 3: Try to access mailbox settings
            # This requires MailboxSettings.Read permission
            print(f"[DEBUG] METHOD 3: Attempting to access mailboxSettings endpoint...")
            settings_response = await client.get(
                f"{GRAPH_API_ENDPOINT}/users/{mailbox_email}/mailboxSettings",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )
            
            if settings_response.status_code == 200:
                print(f"[DEBUG] ✓ METHOD 3 PASSED: Successfully accessed mailboxSettings for {mailbox_email}")
                return True
            
            # Log the error for debugging
            settings_error = ""
            try:
                settings_error_body = settings_response.json()
                settings_error = f" - {settings_error_body}"
            except:
                settings_error = f" - {settings_response.text[:200]}"
            print(f"[DEBUG] METHOD 3 FAILED: Cannot access mailboxSettings for {mailbox_email}: Status {settings_response.status_code}{settings_error}")
            
            # Method 4: Fallback - Try to list messages in inbox (alternative check for FullAccess)
            print(f"[DEBUG] METHOD 4: Attempting to access inbox messages...")
            messages_response = await client.get(
                f"{GRAPH_API_ENDPOINT}/users/{mailbox_email}/mailFolders/inbox/messages?$top=1",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )
            
            if messages_response.status_code == 200:
                print(f"[DEBUG] ✓ METHOD 4 PASSED: Successfully accessed messages for {mailbox_email} - FullAccess confirmed")
                return True
            
            # Log the error for debugging
            messages_error = ""
            try:
                messages_error_body = messages_response.json()
                messages_error = f" - {messages_error_body}"
            except:
                messages_error = f" - {messages_response.text[:200]}"
            print(f"[DEBUG] METHOD 4 FAILED: Cannot access messages for {mailbox_email}: Status {messages_response.status_code}{messages_error}")
            
            # Log all errors for final summary
            print(f"[INFO] ========================================")
            print(f"[INFO] Mailbox access check FAILED for {mailbox_email}")
            print(f"[INFO] ========================================")
            print(f"[INFO] METHOD 2 (inbox folder): Status {inbox_response.status_code}{inbox_error}")
            print(f"[INFO] METHOD 3 (mailboxSettings): Status {settings_response.status_code}{settings_error}")
            print(f"[INFO] METHOD 4 (inbox messages): Status {messages_response.status_code}{messages_error}")
            print(f"[INFO] ========================================")
            print(f"[INFO] All access checks returned 403 ErrorAccessDenied")
            print(f"[INFO] ========================================")
            print(f"[INFO] POSSIBLE CAUSES:")
            print(f"[INFO] 1. User does not have FullAccess/SendAs/SendOnBehalf permission on the mailbox")
            print(f"[INFO] 2. Application Access Policy is blocking access (check Exchange Admin Center)")
            print(f"[INFO] 3. Mailbox permissions haven't propagated (wait 5-10 minutes)")
            print(f"[INFO] 4. The mailbox email address is incorrect: {mailbox_email}")
            print(f"[INFO] 5. The Azure App Registration needs Application Access Policy configuration")
            print(f"[INFO] ========================================")
            print(f"[INFO] TROUBLESHOOTING STEPS:")
            print(f"[INFO] 1. Verify user has FullAccess in Exchange Admin Center:")
            print(f"[INFO]    Exchange Admin Center → Recipients → Mailboxes → {mailbox_email} → Manage mailbox delegation")
            print(f"[INFO] 2. Check Application Access Policies in Exchange Online PowerShell:")
            print(f"[INFO]    Get-ApplicationAccessPolicy")
            print(f"[INFO] 3. If policies exist, ensure your app (Client ID: ab608ebc-7163-416a-ba6d-fb2f885d8914) is allowed")
            print(f"[INFO] 4. Wait 5-10 minutes after granting permissions for propagation")
            print(f"[INFO] ========================================")
            
            return False
            
    except httpx.TimeoutException:
        print(f"[ERROR] Timeout while checking mailbox access for {mailbox_email}")
        # On timeout, deny access for security
        return False
    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f"[ERROR] Failed to check mailbox access for {mailbox_email}: {e}")
        print(f"[ERROR] Full traceback:\n{error_traceback}")
        # On error, deny access for security
        return False


@app.get("/login/azure")
async def login_azure(request: Request):
    """Initiate Azure AD SSO login"""
    from authAzure import AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_REDIRECT_URI, AZURE_AUTHORIZATION_ENDPOINT
    import secrets
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Store state in both session and cache (cache as backup)
    try:
        # Initialize session by accessing it
        _ = request.session
        # Store the state in session
        request.session["azure_oauth_state"] = state
    except Exception:
        # If session fails, we'll rely on cache only
        pass
    
    # Also store in cache as backup (works even if session cookie fails)
    _store_oauth_state(state)
    
    # Determine redirect URI dynamically based on the request host
    # This allows the app to work both locally and via ngrok
    host = request.headers.get("host", "")
    if host and "ngrok" in host.lower():
        # Using ngrok - construct redirect URI from the request
        scheme = "https"  # ngrok always uses HTTPS
        redirect_uri = f"{scheme}://{host}/auth/callback"
    else:
        # Using localhost or direct access - use configured redirect URI
        redirect_uri = AZURE_REDIRECT_URI
    
    # Build authorization URL
    # Use custom API scopes for general SSO authentication
    scope = "openid profile email api://ab608ebc-7163-416a-ba6d-fb2f885d8914/userImpersonations"
    
    params = {
        "client_id": AZURE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": scope,
        "state": state,
        "prompt": "select_account",  # Force account selection screen
    }
    
    auth_url = f"{AZURE_AUTHORIZATION_ENDPOINT}?" + "&".join([f"{k}={v}" for k, v in params.items()])
    
    # Create redirect response
    # The SessionMiddleware will save the session when this response is processed
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@app.get("/auth/callback")
async def azure_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handle Azure AD OAuth callback"""
    from authAzure import AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, AZURE_REDIRECT_URI, AZURE_TOKEN_ENDPOINT
    import httpx
    
    if error:
        return RedirectResponse(url=f"/login?error=azure_{error}", status_code=status.HTTP_302_FOUND)
    
    if not code:
        return RedirectResponse(url="/login?error=no_code", status_code=status.HTTP_302_FOUND)
    
    # Verify state (CSRF protection)
    if not state:
        return RedirectResponse(url="/login?error=no_state", status_code=status.HTTP_302_FOUND)
    
    # Try to get state from session first
    stored_state = None
    try:
        _ = request.session  # Force session initialization
        stored_state = request.session.get("azure_oauth_state")
    except Exception:
        # Session might not be accessible, that's okay - we'll check cache
        pass
    
    # If not in session, check cache (backup mechanism)
    state_valid = False
    if stored_state and state == stored_state:
        state_valid = True
    elif _verify_oauth_state(state):
        # State found in cache, valid
        state_valid = True
        # Also try to update session if possible
        try:
            request.session["azure_oauth_state"] = state
        except Exception:
            pass
    
    if not state_valid:
        print(f"[WARNING] State verification failed. Received state from Azure: {state[:20]}...")
        return RedirectResponse(url="/login?error=invalid_state", status_code=status.HTTP_302_FOUND)
    
    # Determine redirect URI dynamically based on the request host
    # This must match what was used in the authorization request
    host = request.headers.get("host", "")
    if host and "ngrok" in host.lower():
        # Using ngrok - construct redirect URI from the request
        scheme = "https"  # ngrok always uses HTTPS
        redirect_uri = f"{scheme}://{host}/auth/callback"
    else:
        # Using localhost or direct access - use configured redirect URI
        redirect_uri = AZURE_REDIRECT_URI
    
    try:
        # Exchange authorization code for access token
        # Azure AD uses the scopes from the authorization request automatically
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                AZURE_TOKEN_ENDPOINT,
                data={
                    "client_id": AZURE_CLIENT_ID,
                    "client_secret": AZURE_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            
            if token_response.status_code != 200:
                error_detail = f"Token exchange failed with status {token_response.status_code}"
                try:
                    error_body = token_response.json()
                    error_detail += f": {error_body}"
                    print(f"[ERROR] Token exchange error: {error_detail}")
                except:
                    error_text = token_response.text[:500]  # Limit error text length
                    error_detail += f": {error_text}"
                    print(f"[ERROR] Token exchange error: {error_detail}")
                return RedirectResponse(url=f"/login?error=token_exchange_failed", status_code=status.HTTP_302_FOUND)
            
            token_data = token_response.json()
            access_token = token_data.get("access_token")
            id_token = token_data.get("id_token")
            
            # Debug: Log the scopes in the token (if available)
            if "scope" in token_data:
                print(f"[DEBUG] Token scopes: {token_data.get('scope')}")
            
            if not access_token:
                print(f"[ERROR] No access token in response: {token_data}")
                return RedirectResponse(url="/login?error=no_access_token", status_code=status.HTTP_302_FOUND)
            
            if not id_token:
                print(f"[ERROR] No ID token in response: {token_data}")
                return RedirectResponse(url="/login?error=no_id_token", status_code=status.HTTP_302_FOUND)
            
            # Get user info from ID token
            try:
                import jwt
                from authAzure import AZURE_CLIENT_ID, AZURE_TENANT_ID
                
                # Decode ID token (without verification for now - in production, verify the signature)
                # For production, you should verify the token signature using Azure's public keys
                user_info = jwt.decode(
                    id_token,
                    options={"verify_signature": False}  # In production, verify signature
                )
                
                # Extract username/email
                username = (
                    user_info.get("preferred_username") or 
                    user_info.get("email") or 
                    user_info.get("upn") or 
                    user_info.get("name") or 
                    "azure_user"
                )
            except Exception as e:
                # Fallback: simple base64 decode
                import base64
                import json
                try:
                    id_token_parts = id_token.split('.')
                    if len(id_token_parts) >= 2:
                        payload = id_token_parts[1]
                        payload += '=' * (4 - len(payload) % 4)
                        decoded = base64.urlsafe_b64decode(payload)
                        user_info = json.loads(decoded)
                        username = user_info.get("preferred_username") or user_info.get("email") or "azure_user"
                    else:
                        username = "azure_user"
                except:
                    username = "azure_user"
            
            # Create session token
            session_token = create_session_token(username)
            
            # Clear the state from both session and cache
            try:
                request.session.pop("azure_oauth_state", None)
            except Exception:
                pass
            _remove_oauth_state(state)
            
            # Create response and set cookie
            # Determine if we're in production (HTTPS) or development (HTTP)
            is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"
            use_https = request.url.scheme == "https" or is_production
            
            response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
            response.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_token,
                httponly=True,
                secure=use_https,  # Only use secure cookies in production/HTTPS
                samesite="lax",
                max_age=86400  # 24 hours
            )
            return response
            
    except Exception as e:
        # Log the full error with traceback for debugging
        error_traceback = traceback.format_exc()
        print(f"[ERROR] Azure auth error: {e}")
        print(f"[ERROR] Full traceback:\n{error_traceback}")
        
        # Provide more specific error messages based on error type
        error_message = "auth_failed"
        if "client_secret" in str(e).lower() or "invalid_client" in str(e).lower():
            error_message = "invalid_client_config"
        elif "token" in str(e).lower():
            error_message = "token_error"
        elif "mailbox" in str(e).lower():
            error_message = "mailbox_check_failed"
        
        return RedirectResponse(url=f"/login?error={error_message}", status_code=status.HTTP_302_FOUND)


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login form submission"""
    if verify_user(username, password):
        # Create session token
        session_token = create_session_token(username)
        
        # Create response and set cookie
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=86400  # 24 hours
        )
        return response
    else:
        return RedirectResponse(url="/login?error=invalid_credentials", status_code=status.HTTP_302_FOUND)


@app.get("/logout")
async def logout():
    """Handle logout"""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, current_user: str = Depends(require_auth)):
    """Home page with navigation to both stages"""
    return templates.TemplateResponse("home.html", {"request": request, "username": current_user})


@app.get("/stage1", response_class=HTMLResponse)
async def stage1_page(request: Request, current_user: str = Depends(require_auth)):
    """Data Preparation: XLSX to CSV conversion page"""
    return templates.TemplateResponse("stage1.html", {"request": request})


@app.post("/api/convert-xlsx")
async def convert_xlsx(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """
    Data Preparation: Convert XLSX file to multiple CSV files and store them for download or invoice creation
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")
    
    # Create a conversion session
    conversion_session_id = os.urandom(16).hex()
    temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"convert_{conversion_session_id}_")
    
    try:
        xlsx_path = os.path.join(temp_dir, file.filename)
        with open(xlsx_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Convert xlsx to CSV
        base_name = Path(file.filename).stem
        xlsx_to_csv(xlsx_path, temp_dir)
        # xlsx_to_csv creates a subdirectory with the base_name
        output_dir = os.path.join(temp_dir, base_name)
        
        # Get list of CSV files created
        csv_files = []
        if os.path.exists(output_dir):
            for root, dirs, files in os.walk(output_dir):
                for csv_file in files:
                    if csv_file.endswith('.csv'):
                        file_path = os.path.join(root, csv_file)
                        csv_files.append({
                            'filename': csv_file,
                            'path': file_path
                        })
        
        # Return session info with file list
        return JSONResponse({
            'session_id': conversion_session_id,
            'base_name': base_name,
            'file_count': len(csv_files),
            'files': [f['filename'] for f in csv_files]
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.post("/api/convert-csv")
async def convert_csv(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """
    Data Preparation: Split CSV file by BudgetCodeText column and store them for download or invoice creation
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV file (.csv)")
    
    # Create a conversion session
    conversion_session_id = os.urandom(16).hex()
    temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"convert_{conversion_session_id}_")
    
    try:
        csv_path = os.path.join(temp_dir, file.filename)
        with open(csv_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Create output directory for split CSV files
        output_dir = os.path.join(temp_dir, "split_csvs")
        os.makedirs(output_dir, exist_ok=True)
        
        # Split CSV by BudgetCodeText
        split_csv_by_budget_code(csv_path, output_dir)
        
        # Get list of CSV files created
        csv_files = []
        for root, dirs, files in os.walk(output_dir):
            for csv_file in files:
                if csv_file.endswith('.csv'):
                    file_path = os.path.join(root, csv_file)
                    csv_files.append({
                        'filename': csv_file,
                        'path': file_path
                    })
        
        base_name = Path(file.filename).stem
        
        # Return session info with file list
        return JSONResponse({
            'session_id': conversion_session_id,
            'base_name': base_name,
            'file_count': len(csv_files),
            'files': [f['filename'] for f in csv_files]
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.get("/stage2", response_class=HTMLResponse)
async def stage2_page(request: Request, session_id: Optional[str] = None, current_user: str = Depends(require_auth)):
    """Invoice Creation: CSV to Invoice conversion page"""
    return templates.TemplateResponse("stage2.html", {"request": request, "session_id": session_id})


@app.get("/api/download-conversion-zip/{session_id}")
async def download_conversion_zip(session_id: str, current_user: str = Depends(require_auth)):
    """Download ZIP file from a conversion session"""
    # Find the conversion session directory
    conversion_dir = None
    for root, dirs, files in os.walk("temp"):
        for dir_name in dirs:
            if f"convert_{session_id}" in dir_name:
                conversion_dir = os.path.join(root, dir_name)
                break
        if conversion_dir:
            break
    
    if not conversion_dir or not os.path.exists(conversion_dir):
        raise HTTPException(status_code=404, detail="Conversion session not found")
    
    # Find CSV files and create ZIP
    temp_zip_dir = tempfile.mkdtemp(dir="temp")
    zip_path = os.path.join(temp_zip_dir, f"conversion_{session_id}.zip")
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Look for CSV files in subdirectories
            for root, dirs, files in os.walk(conversion_dir):
                for csv_file in files:
                    if csv_file.endswith('.csv'):
                        file_path = os.path.join(root, csv_file)
                        # Use just the filename in the ZIP
                        zipf.write(file_path, csv_file)
        
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"conversion_{session_id}.zip",
            background=None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(e)}")


@app.get("/api/download-conversion-file/{session_id}/{filename:path}")
async def download_conversion_file(session_id: str, filename: str, current_user: str = Depends(require_auth)):
    """Download a single CSV file from a conversion session"""
    # Find the conversion session directory
    conversion_dir = None
    for root, dirs, files in os.walk("temp"):
        for dir_name in dirs:
            if f"convert_{session_id}" in dir_name:
                conversion_dir = os.path.join(root, dir_name)
                break
        if conversion_dir:
            break
    
    if not conversion_dir or not os.path.exists(conversion_dir):
        raise HTTPException(status_code=404, detail="Conversion session not found")
    
    # Find the specific file
    file_path = None
    for root, dirs, files_walk in os.walk(conversion_dir):
        for csv_file in files_walk:
            if csv_file == filename and csv_file.endswith('.csv'):
                file_path = os.path.join(root, csv_file)
                break
        if file_path:
            break
    
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File {filename} not found in conversion session")
    
    return FileResponse(
        file_path,
        media_type="text/csv",
        filename=filename,
        background=None
    )


@app.post("/api/merge-csvs")
async def merge_csvs(files: list[UploadFile] = File(...), filename: Optional[str] = Form(None), current_user: str = Depends(require_auth)):
    """
    Data Preparation: Merge multiple CSV files into one CSV file
    """
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one CSV file is required")
    
    # Validate all files are CSV
    for file in files:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail=f"File {file.filename} must be a CSV file")
    
    # Create a conversion session
    conversion_session_id = os.urandom(16).hex()
    temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"convert_{conversion_session_id}_")
    
    try:
        # Read all CSV files and merge them
        dataframes = []
        for file in files:
            # Save file temporarily
            file_path = os.path.join(temp_dir, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Read CSV into dataframe
            try:
                df = pd.read_csv(file_path)
                dataframes.append(df)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading {file.filename}: {str(e)}")
        
        if not dataframes:
            raise HTTPException(status_code=400, detail="No valid CSV data found")
        
        # Merge all dataframes (concatenate rows)
        merged_df = pd.concat(dataframes, ignore_index=True)
        
        # Determine output filename
        if filename:
            # Remove .csv extension if user included it
            output_filename = filename.replace('.csv', '') + '.csv'
        else:
            output_filename = f"merged_{conversion_session_id[:8]}.csv"
        
        # Save merged CSV
        output_dir = os.path.join(temp_dir, "merged")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)
        merged_df.to_csv(output_path, index=False, encoding='utf-8')
        
        # Return session info
        return JSONResponse({
            'session_id': conversion_session_id,
            'base_name': output_filename.replace('.csv', ''),
            'filename': output_filename,
            'file_count': 1,
            'files': [output_filename],
            'total_rows': len(merged_df)
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error merging files: {str(e)}")


@app.post("/api/merge-csvs-from-session")
async def merge_csvs_from_session(session_id: str = Form(...), files: str = Form(...), filename: Optional[str] = Form(None), current_user: str = Depends(require_auth)):
    """
    Data Preparation: Merge CSV files from a previous conversion session
    """
    import json
    
    try:
        file_list = json.loads(files)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid file list format")
    
    if not file_list or len(file_list) == 0:
        raise HTTPException(status_code=400, detail="At least one file must be selected")
    
    # Find the conversion session directory
    conversion_dir = None
    for root, dirs, files_walk in os.walk("temp"):
        for dir_name in dirs:
            if f"convert_{session_id}" in dir_name:
                conversion_dir = os.path.join(root, dir_name)
                break
        if conversion_dir:
            break
    
    if not conversion_dir or not os.path.exists(conversion_dir):
        raise HTTPException(status_code=404, detail="Conversion session not found")
    
    # Find the CSV files to merge
    csv_files_to_merge = []
    for root, dirs, files_walk in os.walk(conversion_dir):
        for csv_file in files_walk:
            if csv_file.endswith('.csv') and csv_file in file_list:
                file_path = os.path.join(root, csv_file)
                csv_files_to_merge.append(file_path)
    
    if not csv_files_to_merge:
        raise HTTPException(status_code=404, detail="No matching CSV files found in conversion session")
    
    # Create a new conversion session for the merged file
    new_conversion_session_id = os.urandom(16).hex()
    temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"convert_{new_conversion_session_id}_")
    
    try:
        # Read all CSV files and merge them
        dataframes = []
        for file_path in csv_files_to_merge:
            try:
                df = pd.read_csv(file_path)
                dataframes.append(df)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error reading {os.path.basename(file_path)}: {str(e)}")
        
        if not dataframes:
            raise HTTPException(status_code=400, detail="No valid CSV data found")
        
        # Merge all dataframes (concatenate rows)
        merged_df = pd.concat(dataframes, ignore_index=True)
        
        # Determine output filename
        if filename:
            # Remove .csv extension if user included it
            output_filename = filename.replace('.csv', '') + '.csv'
        else:
            output_filename = f"merged_{new_conversion_session_id[:8]}.csv"
        
        # Save merged CSV
        output_dir = os.path.join(temp_dir, "merged")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)
        merged_df.to_csv(output_path, index=False, encoding='utf-8')
        
        # Return session info
        return JSONResponse({
            'session_id': new_conversion_session_id,
            'base_name': output_filename.replace('.csv', ''),
            'filename': output_filename,
            'file_count': 1,
            'files': [output_filename],
            'total_rows': len(merged_df)
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error merging files: {str(e)}")


@app.get("/api/get-conversion-files/{session_id}")
async def get_conversion_files(
    session_id: str, 
    files: Optional[str] = None,
    current_user: str = Depends(require_auth)
):
    """Get CSV files from a conversion session for invoice creation.
    
    Args:
        session_id: The conversion session ID
        files: Optional JSON-encoded list of filenames to filter. If provided, only these files will be included.
    """
    # Find the conversion session directory
    conversion_dir = None
    temp_path = Path("temp")
    
    if not temp_path.exists():
        raise HTTPException(status_code=404, detail="Temp directory not found")
    
    # Search for directory with the session ID
    for root, dirs, files in os.walk("temp"):
        for dir_name in dirs:
            if f"convert_{session_id}" in dir_name:
                conversion_dir = os.path.join(root, dir_name)
                break
        if conversion_dir:
            break
    
    if not conversion_dir or not os.path.exists(conversion_dir):
        raise HTTPException(status_code=404, detail=f"Conversion session not found. Session ID: {session_id}")
    
    # Find all CSV files (they might be in subdirectories like "split_csvs", "merged", or a base_name folder)
    # Exclude the original uploaded file - only include files in subdirectories
    csv_files = []
    original_file_path = None
    
    # First, identify the original file (it's in the root of conversion_dir)
    for item in os.listdir(conversion_dir):
        item_path = os.path.join(conversion_dir, item)
        if os.path.isfile(item_path) and item.endswith('.csv'):
            original_file_path = item_path
            break
    
    # Now collect CSV files, excluding the original
    for root, dirs, files_walk in os.walk(conversion_dir):
        for csv_file in files_walk:
            if csv_file.endswith('.csv'):
                file_path = os.path.join(root, csv_file)
                # Skip the original file (only include files in subdirectories)
                if file_path != original_file_path:
                    csv_files.append(file_path)
    
    # Filter files if a specific list was provided
    selected_filenames = None
    if files:
        try:
            selected_filenames = set(json.loads(files))
            # Filter to only include selected files
            csv_files = [f for f in csv_files if os.path.basename(f) in selected_filenames]
            print(f"[DEBUG] Filtered to {len(csv_files)} selected files from {len(selected_filenames)} requested")
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[WARNING] Failed to parse files parameter: {e}")
    
    print(f"[DEBUG] Found {len(csv_files)} CSV files in conversion session {session_id}")
    if csv_files:
        print(f"[DEBUG] Files: {[os.path.basename(f) for f in csv_files]}")
    
    if not csv_files:
        # Provide more detailed error message
        raise HTTPException(
            status_code=404, 
            detail=f"No CSV files found in conversion session. Searched in: {conversion_dir}"
        )
    
    # Process CSV files similar to upload-csv endpoint
    batch_session_id = os.urandom(16).hex()
    batch_temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"batch_{batch_session_id}_")
    
    invoices = []
    
    for idx, csv_path in enumerate(csv_files):
        try:
            print(f"[DEBUG] Processing CSV file {idx + 1}/{len(csv_files)}: {os.path.basename(csv_path)}")
            # Read and clean CSV
            df = csv_to_dataframe(csv_path)
            
            # Transform to invoice data
            invoice_data = transform_dataframe_to_invoice_data(df)
            
            # Create individual session ID for this invoice
            invoice_session_id = os.urandom(16).hex()
            invoice_data_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_invoice_data.pkl")
            
            with open(invoice_data_path, 'wb') as f:
                pickle.dump(invoice_data, f)
            
            # Serialize invoice_data for JSON response
            serialized_invoice_data = serialize_invoice_data(invoice_data)
            
            csv_filename = os.path.basename(csv_path)
            invoices.append({
                'session_id': invoice_session_id,
                'filename': csv_filename,
                'invoice_data': serialized_invoice_data,
                'index': idx
            })
            print(f"[DEBUG] Successfully processed {csv_filename}")
        except Exception as e:
            print(f"[ERROR] Failed to process {csv_path}: {e}")
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            continue
    
    if not invoices:
        raise HTTPException(status_code=500, detail="Failed to process any CSV files")
    
    return JSONResponse({
        'batch_session_id': batch_session_id,
        'invoices': invoices,
        'total_count': len(invoices)
    })


@app.post("/api/create-combined-session")
async def create_combined_session(files_data: str = Form(...), current_user: str = Depends(require_auth)):
    """
    Create a combined session from files across multiple conversion sessions.
    This is used when users select files from different sessions (e.g., merged file + original division files).
    """
    try:
        files_by_session = json.loads(files_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid files_data format")
    
    if not files_by_session or len(files_by_session) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    
    # Create a new combined conversion session
    combined_session_id = os.urandom(16).hex()
    combined_temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"convert_{combined_session_id}_")
    combined_output_dir = os.path.join(combined_temp_dir, "combined")
    os.makedirs(combined_output_dir, exist_ok=True)
    
    # Copy selected files from each session into the combined session
    for session_id, filenames in files_by_session.items():
        # Find the conversion session directory
        conversion_dir = None
        for root, dirs, files_walk in os.walk("temp"):
            for dir_name in dirs:
                if f"convert_{session_id}" in dir_name:
                    conversion_dir = os.path.join(root, dir_name)
                    break
            if conversion_dir:
                break
        
        if not conversion_dir or not os.path.exists(conversion_dir):
            print(f"[WARNING] Session {session_id} not found, skipping")
            continue
        
        # Find and copy the selected files
        for root, dirs, files_walk in os.walk(conversion_dir):
            for csv_file in files_walk:
                if csv_file.endswith('.csv') and csv_file in filenames:
                    source_path = os.path.join(root, csv_file)
                    dest_path = os.path.join(combined_output_dir, csv_file)
                    shutil.copy2(source_path, dest_path)
                    print(f"[DEBUG] Copied {csv_file} from session {session_id} to combined session")
    
    # Verify files were copied
    copied_files = [f for f in os.listdir(combined_output_dir) if f.endswith('.csv')]
    if not copied_files:
        raise HTTPException(status_code=500, detail="Failed to copy files to combined session")
    
    return JSONResponse({
        'session_id': combined_session_id,
        'file_count': len(copied_files),
        'files': copied_files
    })


@app.get("/stage3", response_class=HTMLResponse)
async def stage3_page(request: Request, current_user: str = Depends(require_auth)):
    """Invoice Editing: Edit saved HTML invoice page"""
    return templates.TemplateResponse("stage3.html", {"request": request})


def serialize_invoice_data(invoice_data):
    """
    Convert invoice_data to JSON-serializable format.
    Handles pandas objects, datetime objects, numpy arrays, and other non-serializable types.
    """
    import pandas as pd
    import numpy as np
    from datetime import datetime, date
    
    def convert_value(value):
        """Recursively convert values to JSON-serializable types"""
        # Handle None first
        if value is None:
            return None
        
        # Handle pandas/numpy array-like objects BEFORE checking pd.isna()
        # pd.isna() on arrays returns an array, which can't be used in if statements
        if isinstance(value, (pd.Series, pd.DataFrame)):
            return value.tolist() if hasattr(value, 'tolist') else str(value)
        
        # Handle numpy arrays
        if isinstance(value, np.ndarray):
            return value.tolist()
        
        # Handle datetime objects
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return value.isoformat() if hasattr(value, 'isoformat') else str(value)
        
        # Handle dictionaries
        if isinstance(value, dict):
            return {k: convert_value(v) for k, v in value.items()}
        
        # Handle lists and tuples
        if isinstance(value, (list, tuple)):
            return [convert_value(item) for item in value]
        
        # Now safe to check for NaN/None on scalar values
        # Only check pd.isna() on scalar types (not arrays)
        try:
            # Check if it's a scalar numeric value that might be NaN
            if isinstance(value, (int, float, complex)):
                if pd.isna(value) or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
                    return None
        except (ValueError, TypeError):
            # If pd.isna() fails (e.g., on arrays), continue to other checks
            pass
        
        # Handle basic types
        if isinstance(value, (str, int, float, bool)):
            return value
        
        # Fallback: convert to string
        return str(value)
    
    return convert_value(invoice_data)


@app.post("/api/upload-csv")
async def upload_csv(files: list[UploadFile] = File(...), current_user: str = Depends(require_auth)):
    """
    Invoice Creation: Upload one or more CSV files, process them, and return invoice data for editing
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one CSV file is required")
    
    # Create a batch session for multiple invoices
    batch_session_id = os.urandom(16).hex()
    batch_temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"batch_{batch_session_id}_")
    
    invoices = []
    
    try:
        for idx, file in enumerate(files):
            if not file.filename.endswith('.csv'):
                raise HTTPException(status_code=400, detail=f"File {file.filename} must be a CSV file")
            
            # Save uploaded file temporarily
            csv_path = os.path.join(batch_temp_dir, file.filename)
            try:
                with open(csv_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
            except Exception as e:
                print(f"[ERROR] Failed to save file {file.filename}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
            
            # Process CSV to invoice data
            try:
                df = csv_to_dataframe(csv_path)
            except Exception as e:
                print(f"[ERROR] Failed to process CSV file {file.filename}: {e}")
                print(f"[ERROR] Traceback: {traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=f"Error reading CSV file {file.filename}: {str(e)}")
            
            try:
                invoice_data = transform_dataframe_to_invoice_data(df)
            except Exception as e:
                print(f"[ERROR] Failed to transform data for {file.filename}: {e}")
                print(f"[ERROR] Traceback: {traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=f"Error transforming data for {file.filename}: {str(e)}")
            
            # Create individual session ID for this invoice
            invoice_session_id = os.urandom(16).hex()
            invoice_data_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_invoice_data.pkl")
            try:
                with open(invoice_data_path, 'wb') as f:
                    pickle.dump(invoice_data, f)
            except Exception as e:
                print(f"[ERROR] Failed to save invoice data for {file.filename}: {e}")
                raise HTTPException(status_code=500, detail=f"Error saving invoice data: {str(e)}")
            
            # Serialize invoice_data for JSON response
            try:
                serialized_invoice_data = serialize_invoice_data(invoice_data)
            except Exception as e:
                print(f"[ERROR] Failed to serialize invoice data for {file.filename}: {e}")
                print(f"[ERROR] Traceback: {traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=f"Error serializing invoice data: {str(e)}")
            
            invoices.append({
                'session_id': invoice_session_id,
                'filename': file.filename,
                'invoice_data': serialized_invoice_data,
                'index': idx
            })
        
        return JSONResponse({
            'batch_session_id': batch_session_id,
            'invoices': invoices,
            'total_count': len(invoices)
        })
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Log full traceback for debugging
        error_traceback = traceback.format_exc()
        print(f"[ERROR] Unexpected error processing CSV files: {e}")
        print(f"[ERROR] Full traceback:\n{error_traceback}")
        raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")


@app.post("/api/upload-html")
async def upload_html(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """
    Invoice Editing: Upload HTML invoice file, parse it, and return invoice data for editing
    """
    if not file.filename.endswith('.html'):
        raise HTTPException(status_code=400, detail="File must be an HTML file (.html)")
    
    # Create a session for this invoice
    invoice_session_id = os.urandom(16).hex()
    batch_temp_dir = tempfile.mkdtemp(dir="temp", prefix=f"html_{invoice_session_id}_")
    
    try:
        # Read HTML content
        html_content = await file.read()
        html_content_str = html_content.decode('utf-8')
        
        # Parse HTML invoice
        invoice_data = parse_html_invoice(html_content_str)
        
        # Save invoice data as pickle
        invoice_data_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_invoice_data.pkl")
        with open(invoice_data_path, 'wb') as f:
            pickle.dump(invoice_data, f)
        
        return JSONResponse({
            'session_id': invoice_session_id,
            'filename': file.filename,
            'invoice_data': invoice_data
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing HTML invoice: {str(e)}")


@app.post("/api/update-invoice")
async def update_invoice(
    session_id: str = Form(...),
    invoice_data_json: str = Form(...),
    current_user: str = Depends(require_auth)
):
    """
    Invoice Creation: Update invoice data and generate HTML
    """
    try:
        invoice_data = json.loads(invoice_data_json)
        
        # Find the temp directory for this session
        temp_dir = None
        invoice_data_path = None
        for root, dirs, files in os.walk("temp"):
            for file in files:
                if file == f"{session_id}_invoice_data.pkl":
                    temp_dir = root
                    invoice_data_path = os.path.join(root, file)
                    break
            if temp_dir:
                break
        
        if not temp_dir or not invoice_data_path:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Save updated invoice data
        with open(invoice_data_path, 'wb') as f:
            pickle.dump(invoice_data, f)
        
        # Generate HTML (template will be selected automatically based on style)
        html_file = generate_invoice_html(
            invoice_data_path,
            template_name=None
        )
        
        # Return the HTML file
        return FileResponse(
            html_file,
            media_type="text/html",
            filename=Path(html_file).name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating invoice: {str(e)}")


@app.post("/api/download-invoice/{session_id}")
async def download_invoice(session_id: str, current_user: str = Depends(require_auth)):
    """
    Download a single invoice HTML file
    """
    try:
        # Find the invoice data file
        invoice_data_path = None
        for root, dirs, files in os.walk("temp"):
            for file in files:
                if file == f"{session_id}_invoice_data.pkl":
                    invoice_data_path = os.path.join(root, file)
                    break
            if invoice_data_path:
                break
        
        if not invoice_data_path:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Load invoice data to get filename
        with open(invoice_data_path, 'rb') as f:
            invoice_data = pickle.load(f)
        
        # Generate HTML if not already generated (template will be selected automatically based on style)
        html_file = generate_invoice_html(
            invoice_data_path,
            template_name=None
        )
        
        return FileResponse(
            html_file,
            media_type="text/html",
            filename=Path(html_file).name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading invoice: {str(e)}")


@app.post("/api/download-all-invoices")
async def download_all_invoices(batch_session_id: str = Form(...), current_user: str = Depends(require_auth)):
    """
    Download all invoices from a batch session as a ZIP file
    """
    try:
        # Find all invoices in the batch session
        batch_dir = None
        invoice_files = []
        
        for root, dirs, files in os.walk("temp"):
            if f"batch_{batch_session_id}" in root:
                batch_dir = root
                for file in files:
                    if file.endswith("_invoice_data.pkl"):
                        invoice_files.append(os.path.join(root, file))
                break
        
        if not batch_dir or not invoice_files:
            raise HTTPException(status_code=404, detail="Batch session not found")
        
        # Generate HTML for all invoices (template will be selected automatically based on style)
        html_files = []
        for invoice_data_path in invoice_files:
            html_file = generate_invoice_html(
                invoice_data_path,
                template_name=None
            )
            html_files.append(html_file)
        
        # Create ZIP file
        zip_path = os.path.join(batch_dir, f"invoices_{batch_session_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for html_file in html_files:
                zipf.write(html_file, Path(html_file).name)
        
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"invoices_{batch_session_id}.zip"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(e)}")


@app.get("/api/invoice-preview/{session_id}")
async def invoice_preview(session_id: str, current_user: str = Depends(require_auth)):
    """
    Preview the invoice HTML for a session
    """
    # Find the invoice data file
    invoice_data_path = None
    for root, dirs, files in os.walk("temp"):
        for file in files:
            if file == f"{session_id}_invoice_data.pkl":
                invoice_data_path = os.path.join(root, file)
                break
        if invoice_data_path:
            break
    
    if not invoice_data_path:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Load invoice data
    with open(invoice_data_path, 'rb') as f:
        invoice_data = pickle.load(f)
    
    # Determine template based on style
    style = invoice_data.get('style', 'style1')
    if style == 'style2':
        template_name = 'Invoice 2 - Style 2.html'
    else:
        template_name = 'Invoice 2.html'
    
    # Set up Jinja2 environment
    templates_dir = Path(__file__).parent / 'templates'
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    env.filters['format_date'] = format_date_word_format  # Invoice header date in word format
    env.filters['format_date_numeric'] = format_date_dd_mm_yyyy  # Line item dates in numeric format
    env.filters['format_currency'] = format_currency  # Format numbers with commas and 2 decimal places
    template = env.get_template(template_name)
    
    # Render the template (keep static path for preview since FastAPI serves static files)
    html_content = template.render(data=invoice_data)
    
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

