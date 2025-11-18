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

app = FastAPI(title="Batch Invoicer", description="Convert XLSX to CSV and generate invoices")

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


def generate_invoice_html(invoice_data_path: str, template_name: str = 'Invoice 2.html', embed_image: bool = True) -> str:
    """Generate HTML invoice from invoice data pickle file"""
    import base64
    
    # Load invoice data
    with open(invoice_data_path, 'rb') as f:
        invoice_data = pickle.load(f)
    
    # Set up Jinja2 environment
    templates_dir = Path(__file__).parent / 'templates'
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template(template_name)
    
    # Render the template
    rendered_html = template.render(data=invoice_data)
    
    # Fix image path for standalone HTML
    templates_img = Path(__file__).parent / 'templates' / 'Picture1.jpg'
    static_img = Path(__file__).parent / 'static' / 'Picture1.jpg'
    
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
                rendered_html = rendered_html.replace('/static/Picture1.jpg', img_base64)
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
        
        # Generate HTML
        html_file = generate_invoice_html(
            invoice_data_path,
            template_name='Invoice 2.html'
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
        
        # Generate HTML if not already generated
        html_file = generate_invoice_html(
            invoice_data_path,
            template_name='Invoice 2.html'
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
        
        # Generate HTML for all invoices
        html_files = []
        for invoice_data_path in invoice_files:
            html_file = generate_invoice_html(
                invoice_data_path,
                template_name='Invoice 2.html'
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
    
    # Set up Jinja2 environment
    templates_dir = Path(__file__).parent / 'templates'
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template('Invoice 2.html')
    
    # Render the template (keep static path for preview since FastAPI serves static files)
    html_content = template.render(data=invoice_data)
    
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

