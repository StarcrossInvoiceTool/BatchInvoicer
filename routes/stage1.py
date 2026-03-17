"""Stage 1 routes: XLSX/CSV conversion, download, and merge."""

import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

import config
import session_manager
from dependencies import templates, require_auth
from divider import split_csv_by_budget_code
from models import ConversionResponse, MergeResponse, parse_json_string_list
from services.csv_service import merge_csv_dataframes, save_merged_csv
from xslx_to_csv import xlsx_to_csv

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stage1", response_class=HTMLResponse)
async def stage1_page(request: Request, current_user: str = Depends(require_auth)):
    """Data Preparation: XLSX to CSV conversion page."""
    return templates.TemplateResponse("stage1.html", {"request": request})


@router.post("/api/convert-xlsx", response_model=ConversionResponse)
async def convert_xlsx(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """Convert XLSX file to multiple CSV files."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")

    conversion_session_id, temp_dir = session_manager.create_session_dir("convert_")

    try:
        xlsx_path = os.path.join(temp_dir, file.filename)
        with open(xlsx_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        base_name = Path(file.filename).stem
        xlsx_to_csv(xlsx_path, temp_dir)
        output_dir = os.path.join(temp_dir, base_name)

        csv_files = []
        if os.path.exists(output_dir):
            for root, dirs, files in os.walk(output_dir):
                for csv_file in files:
                    if csv_file.endswith('.csv'):
                        csv_files.append(csv_file)

        return {
            'session_id': conversion_session_id,
            'base_name': base_name,
            'file_count': len(csv_files),
            'files': csv_files,
        }
    except (FileNotFoundError, OSError, ValueError) as e:
        logger.exception("Error converting XLSX file")
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@router.post("/api/convert-csv", response_model=ConversionResponse)
async def convert_csv(file: UploadFile = File(...), current_user: str = Depends(require_auth)):
    """Split CSV file by BudgetCodeText column."""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV file (.csv)")

    conversion_session_id, temp_dir = session_manager.create_session_dir("convert_")

    try:
        csv_path = os.path.join(temp_dir, file.filename)
        with open(csv_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        output_dir = os.path.join(temp_dir, "split_csvs")
        os.makedirs(output_dir, exist_ok=True)
        split_csv_by_budget_code(csv_path, output_dir)

        csv_files = []
        for root, dirs, files in os.walk(output_dir):
            for csv_file in files:
                if csv_file.endswith('.csv'):
                    csv_files.append(csv_file)

        base_name = Path(file.filename).stem
        return {
            'session_id': conversion_session_id,
            'base_name': base_name,
            'file_count': len(csv_files),
            'files': csv_files,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (FileNotFoundError, OSError) as e:
        logger.exception("Error splitting CSV file")
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@router.get("/api/download-conversion-zip/{session_id}")
async def download_conversion_zip(session_id: str, current_user: str = Depends(require_auth)):
    """Download ZIP file from a conversion session."""
    conversion_dir = session_manager.find_conversion_dir(session_id)
    if not conversion_dir:
        raise HTTPException(status_code=404, detail="Conversion session not found")

    temp_zip_dir = tempfile.mkdtemp(dir=config.TEMP_DIR)
    zip_path = os.path.join(temp_zip_dir, f"conversion_{session_id}.zip")

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(conversion_dir):
                for csv_file in files:
                    if csv_file.endswith('.csv'):
                        zipf.write(os.path.join(root, csv_file), csv_file)

        return FileResponse(zip_path, media_type="application/zip", filename=f"conversion_{session_id}.zip", background=None)
    except (OSError, zipfile.BadZipFile) as e:
        logger.exception("Error creating conversion ZIP for %s", session_id)
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(e)}")


@router.get("/api/download-conversion-file/{session_id}/{filename:path}")
async def download_conversion_file(session_id: str, filename: str, current_user: str = Depends(require_auth)):
    """Download a single CSV file from a conversion session."""
    conversion_dir = session_manager.find_conversion_dir(session_id)
    if not conversion_dir:
        raise HTTPException(status_code=404, detail="Conversion session not found")

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

    return FileResponse(file_path, media_type="text/csv", filename=filename, background=None)


@router.post("/api/merge-csvs", response_model=MergeResponse)
async def merge_csvs(files: list[UploadFile] = File(...), filename: Optional[str] = Form(None), current_user: str = Depends(require_auth)):
    """Merge multiple CSV files into one CSV file."""
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one CSV file is required")

    for file in files:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail=f"File {file.filename} must be a CSV file")

    conversion_session_id, temp_dir = session_manager.create_session_dir("convert_")

    try:
        saved_paths = []
        for file in files:
            file_path = os.path.join(temp_dir, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_paths.append(file_path)

        merged_df = merge_csv_dataframes(saved_paths)
        return save_merged_csv(merged_df, conversion_session_id, temp_dir, filename)
    except HTTPException:
        raise
    except (OSError, ValueError, pd.errors.EmptyDataError) as e:
        logger.exception("Error merging uploaded CSV files")
        raise HTTPException(status_code=500, detail=f"Error merging files: {str(e)}")


@router.post("/api/merge-csvs-from-session", response_model=MergeResponse)
async def merge_csvs_from_session(
    session_id: str = Form(...),
    files: str = Form(...),
    filename: Optional[str] = Form(None),
    current_user: str = Depends(require_auth),
):
    """Merge CSV files from a previous conversion session."""
    file_list = parse_json_string_list(files, "file list")

    if not file_list or len(file_list) == 0:
        raise HTTPException(status_code=400, detail="At least one file must be selected")

    conversion_dir = session_manager.find_conversion_dir(session_id)
    if not conversion_dir:
        raise HTTPException(status_code=404, detail="Conversion session not found")

    csv_files_to_merge = []
    for root, dirs, files_walk in os.walk(conversion_dir):
        for csv_file in files_walk:
            if csv_file.endswith('.csv') and csv_file in file_list:
                csv_files_to_merge.append(os.path.join(root, csv_file))

    if not csv_files_to_merge:
        raise HTTPException(status_code=404, detail="No matching CSV files found in conversion session")

    new_conversion_session_id, temp_dir = session_manager.create_session_dir("convert_")

    try:
        merged_df = merge_csv_dataframes(csv_files_to_merge)
        return save_merged_csv(merged_df, new_conversion_session_id, temp_dir, filename)
    except HTTPException:
        raise
    except (OSError, ValueError, pd.errors.EmptyDataError) as e:
        logger.exception("Error merging session CSV files")
        raise HTTPException(status_code=500, detail=f"Error merging files: {str(e)}")
