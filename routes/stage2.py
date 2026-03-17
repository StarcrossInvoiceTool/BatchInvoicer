"""Stage 2 routes: invoice creation from CSVs, combined sessions, upload CSV/HTML."""

import logging
import os
import pickle
import shutil
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

import session_manager
from csv_cleaner import csv_to_dataframe
from DataScraper import transform_dataframe_to_invoice_data
from dependencies import templates, require_auth
from models import (
    BatchInvoicesResponse,
    CombinedSessionResponse,
    UploadHtmlResponse,
    parse_json_dict,
)
from services.csv_service import collect_conversion_csvs, process_csv_to_invoice
from services.invoice_service import parse_html_invoice, serialize_invoice_data

router = APIRouter()


@router.get("/stage2", response_class=HTMLResponse)
async def stage2_page(request: Request, session_id: Optional[str] = None, current_user: str = Depends(require_auth)):
    """Invoice Creation: CSV to Invoice conversion page."""
    return templates.TemplateResponse("stage2.html", {"request": request, "session_id": session_id})


@router.get("/api/get-conversion-files/{session_id}", response_model=BatchInvoicesResponse)
async def get_conversion_files(
    session_id: str,
    files: Optional[str] = None,
    current_user: str = Depends(require_auth),
):
    """Get CSV files from a conversion session for invoice creation."""
    conversion_dir = session_manager.find_conversion_dir(session_id)
    if not conversion_dir:
        raise HTTPException(status_code=404, detail=f"Conversion session not found. Session ID: {session_id}")

    csv_files = collect_conversion_csvs(conversion_dir, files)
    if not csv_files:
        raise HTTPException(status_code=404, detail=f"No CSV files found in conversion session. Searched in: {conversion_dir}")

    batch_session_id, batch_temp_dir = session_manager.create_session_dir("batch_")

    invoices = []
    for idx, csv_path in enumerate(csv_files):
        try:
            result = process_csv_to_invoice(csv_path, batch_temp_dir, idx)
            invoices.append(result)
        except (ValueError, OSError, pd.errors.ParserError) as e:
            logger.exception("Failed to process %s", csv_path)
            continue

    if not invoices:
        raise HTTPException(status_code=500, detail="Failed to process any CSV files")

    return {
        'batch_session_id': batch_session_id,
        'invoices': invoices,
        'total_count': len(invoices),
    }


@router.post("/api/create-combined-session", response_model=CombinedSessionResponse)
async def create_combined_session(files_data: str = Form(...), current_user: str = Depends(require_auth)):
    """Create a combined session from files across multiple conversion sessions."""
    files_by_session = parse_json_dict(files_data, "files_data")

    if not files_by_session or len(files_by_session) == 0:
        raise HTTPException(status_code=400, detail="No files provided")

    combined_session_id, combined_temp_dir = session_manager.create_session_dir("convert_")
    combined_output_dir = os.path.join(combined_temp_dir, "combined")
    os.makedirs(combined_output_dir, exist_ok=True)

    for sid, filenames in files_by_session.items():
        conversion_dir = session_manager.find_conversion_dir(sid)
        if not conversion_dir:
            logger.warning("Session %s not found, skipping", sid)
            continue
        for root, dirs, files_walk in os.walk(conversion_dir):
            for csv_file in files_walk:
                if csv_file.endswith('.csv') and csv_file in filenames:
                    shutil.copy2(os.path.join(root, csv_file), os.path.join(combined_output_dir, csv_file))

    copied_files = [f for f in os.listdir(combined_output_dir) if f.endswith('.csv')]
    if not copied_files:
        raise HTTPException(status_code=500, detail="Failed to copy files to combined session")

    return {
        'session_id': combined_session_id,
        'file_count': len(copied_files),
        'files': copied_files,
    }


@router.post("/api/upload-csv", response_model=BatchInvoicesResponse)
async def upload_csv(files: list[UploadFile] = File(...), current_user: str = Depends(require_auth)):
    """Upload one or more CSV files, process them, and return invoice data for editing."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one CSV file is required")

    batch_session_id, batch_temp_dir = session_manager.create_session_dir("batch_")
    invoices = []

    try:
        for idx, file in enumerate(files):
            if not file.filename.endswith('.csv'):
                raise HTTPException(status_code=400, detail=f"File {file.filename} must be a CSV file")

            csv_path = os.path.join(batch_temp_dir, file.filename)
            try:
                with open(csv_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
            except OSError as e:
                raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

            try:
                df = csv_to_dataframe(csv_path)
            except (FileNotFoundError, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as e:
                raise HTTPException(status_code=500, detail=f"Error reading CSV file {file.filename}: {str(e)}")

            try:
                invoice_data = transform_dataframe_to_invoice_data(df)
            except (ValueError, KeyError) as e:
                raise HTTPException(status_code=500, detail=f"Error transforming data for {file.filename}: {str(e)}")

            invoice_session_id = os.urandom(16).hex()
            invoice_data_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_invoice_data.pkl")
            source_csv_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_source.csv")

            try:
                with open(invoice_data_path, 'wb') as f:
                    pickle.dump(invoice_data, f)
            except (OSError, pickle.PicklingError) as e:
                raise HTTPException(status_code=500, detail=f"Error saving invoice data: {str(e)}")

            try:
                shutil.copy2(csv_path, source_csv_path)
                with open(os.path.join(batch_temp_dir, f"{invoice_session_id}_source_filename.txt"), "w", encoding="utf-8") as fn:
                    fn.write(file.filename)
                source_headers = list(pd.read_csv(source_csv_path, nrows=0).columns)
            except (OSError, pd.errors.ParserError):
                source_headers = list(df.columns)

            try:
                serialized_invoice_data = serialize_invoice_data(invoice_data)
            except (TypeError, ValueError) as e:
                raise HTTPException(status_code=500, detail=f"Error serializing invoice data: {str(e)}")

            invoices.append({
                'session_id': invoice_session_id,
                'filename': file.filename,
                'invoice_data': serialized_invoice_data,
                'source_headers': source_headers,
                'index': idx,
            })

        return {
            'batch_session_id': batch_session_id,
            'invoices': invoices,
            'total_count': len(invoices),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error processing CSV files")
        raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")


@router.post("/api/upload-html", response_model=UploadHtmlResponse)
async def upload_html(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """Upload HTML invoice file, parse it, and return invoice data for editing."""
    if not file.filename.endswith('.html'):
        raise HTTPException(status_code=400, detail="File must be an HTML file (.html)")

    invoice_session_id, batch_temp_dir = session_manager.create_session_dir("html_")

    try:
        html_content = await file.read()
        html_content_str = html_content.decode('utf-8')
        invoice_data = parse_html_invoice(html_content_str)

        invoice_data_path = os.path.join(batch_temp_dir, f"{invoice_session_id}_invoice_data.pkl")
        with open(invoice_data_path, 'wb') as f:
            pickle.dump(invoice_data, f)

        return {
            'session_id': invoice_session_id,
            'filename': file.filename,
            'invoice_data': invoice_data,
        }
    except (UnicodeDecodeError, ValueError, OSError) as e:
        logger.exception("Error processing HTML invoice")
        raise HTTPException(status_code=500, detail=f"Error processing HTML invoice: {str(e)}")
