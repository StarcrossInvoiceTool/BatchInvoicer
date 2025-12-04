from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import os
import zipfile
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import pickle
from typing import Optional
import json

from xslx_to_csv import xlsx_to_csv
from csv_cleaner import csv_to_dataframe
from DataScraper import transform_dataframe_to_invoice_data
from jinja2 import Environment, FileSystemLoader
from auth import verify_user, create_session_token, verify_session_token, SESSION_COOKIE_NAME
from bs4 import BeautifulSoup
import re
from datetime import datetime

app = FastAPI(title="Batch Invoicer", description="Convert XLSX to CSV and generate invoices")

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
templates = Jinja2Templates(directory="templates")


# Authentication dependency
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
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


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
    """Stage 1: XLSX to CSV conversion page"""
    return templates.TemplateResponse("stage1.html", {"request": request})


@app.post("/api/convert-xlsx")
async def convert_xlsx(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """
    Stage 1: Convert XLSX file to multiple CSV files and return as ZIP
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")
    
    # Save uploaded file temporarily
    temp_dir = tempfile.mkdtemp(dir="temp")
    try:
        xlsx_path = os.path.join(temp_dir, file.filename)
        with open(xlsx_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Convert xlsx to CSV
        base_name = Path(file.filename).stem
        xlsx_to_csv(xlsx_path, temp_dir)
        output_dir = os.path.join(temp_dir, base_name)
        
        # Create ZIP file
        zip_path = os.path.join(temp_dir, f"{base_name}_csvs.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(output_dir):
                for csv_file in files:
                    if csv_file.endswith('.csv'):
                        file_path = os.path.join(root, csv_file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
        
        # Return ZIP file
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"{base_name}_csvs.zip",
            background=None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
    finally:
        # Cleanup will happen after file is sent
        pass


@app.get("/stage2", response_class=HTMLResponse)
async def stage2_page(request: Request, current_user: str = Depends(require_auth)):
    """Stage 2: CSV to Invoice conversion page"""
    return templates.TemplateResponse("stage2.html", {"request": request})


@app.get("/stage3", response_class=HTMLResponse)
async def stage3_page(request: Request, current_user: str = Depends(require_auth)):
    """Stage 3: Edit saved HTML invoice page"""
    return templates.TemplateResponse("stage3.html", {"request": request})


@app.post("/api/upload-csv")
async def upload_csv(files: list[UploadFile] = File(...), current_user: str = Depends(require_auth)):
    """
    Stage 2: Upload one or more CSV files, process them, and return invoice data for editing
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
            with open(csv_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Process CSV to invoice data
            df = csv_to_dataframe(csv_path)
            invoice_data = transform_dataframe_to_invoice_data(df)
            
            # Create individual session ID for this invoice
            invoice_session_id = os.urandom(16).hex()
            invoice_data_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_invoice_data.pkl")
            with open(invoice_data_path, 'wb') as f:
                pickle.dump(invoice_data, f)
            
            invoices.append({
                'session_id': invoice_session_id,
                'filename': file.filename,
                'invoice_data': invoice_data,
                'index': idx
            })
        
        return JSONResponse({
            'batch_session_id': batch_session_id,
            'invoices': invoices,
            'total_count': len(invoices)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")


@app.post("/api/upload-html")
async def upload_html(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """
    Stage 3: Upload HTML invoice file, parse it, and return invoice data for editing
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
    Stage 2: Update invoice data and generate HTML
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
    template = env.get_template(template_name)
    
    # Render the template (keep static path for preview since FastAPI serves static files)
    html_content = template.render(data=invoice_data)
    
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

