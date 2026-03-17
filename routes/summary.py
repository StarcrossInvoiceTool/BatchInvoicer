"""Summary routes: template upload, column mapping, status, calculated fields, and summary editor."""

import json
import logging
import os
import pickle

import pandas as pd
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

import session_manager

logger = logging.getLogger(__name__)
from dependencies import require_auth
from models import (
    CalculatedFieldsResponse,
    SummaryMappingResponse,
    SummaryTemplateStatusResponse,
    SummaryTemplateUploadResponse,
    parse_json_dict,
)
from services.summary_service import (
    SUMMARY_CALCULATED_FIELDS,
    build_merged_summary,
    ensure_line_item_charges,
)

import config

templates = Jinja2Templates(directory=str(config.BASE_DIR / config.TEMPLATES_DIR))

router = APIRouter()


@router.get("/api/summary-calculated-fields", response_model=CalculatedFieldsResponse)
async def get_summary_calculated_fields(current_user: str = Depends(require_auth)):
    """Return calculated/synthetic fields that can be mapped to summary columns."""
    return {"fields": SUMMARY_CALCULATED_FIELDS}


@router.post("/api/upload-summary-template", response_model=SummaryTemplateUploadResponse)
async def upload_summary_template(
    batch_session_id: str = Form(...),
    invoice_session_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: str = Depends(require_auth),
):
    """Upload the empty/template CSV for the summary sheet.

    Saves it per-invoice so each invoice can have its own summary template.
    Returns the column headers so the client can show the column-mapping modal.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    batch_dir = session_manager.find_batch_dir(batch_session_id)
    if not batch_dir:
        raise HTTPException(status_code=404, detail="Batch session not found")

    path = os.path.join(batch_dir, f"summary_template_{invoice_session_id}.csv")
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    name_path = os.path.join(batch_dir, f"summary_template_filename_{invoice_session_id}.txt")
    with open(name_path, "w", encoding="utf-8") as f:
        f.write(file.filename or "summary_template.csv")

    try:
        df = pd.read_csv(path, nrows=0)
        columns = list(df.columns)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {str(e)}")

    return {"columns": columns, "template_filename": file.filename}


@router.post("/api/set-summary-mapping", response_model=SummaryMappingResponse)
async def set_summary_mapping(
    batch_session_id: str = Form(...),
    invoice_session_id: str = Form(...),
    mapping: str = Form(...),
    current_user: str = Depends(require_auth),
):
    """Save the column mapping (summary column -> source CSV column) per invoice."""
    batch_dir = session_manager.find_batch_dir(batch_session_id)
    if not batch_dir:
        raise HTTPException(status_code=404, detail="Batch session not found")
    mapping_obj = parse_json_dict(mapping, "mapping")

    path = os.path.join(batch_dir, f"summary_mapping_{invoice_session_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping_obj, f, indent=2)
    return {"ok": True}


@router.get("/api/summary-template-status/{batch_session_id}/{invoice_session_id}", response_model=SummaryTemplateStatusResponse)
async def summary_template_status(
    batch_session_id: str,
    invoice_session_id: str,
    current_user: str = Depends(require_auth),
):
    """Return whether a summary template and mapping exist for this invoice."""
    batch_dir = session_manager.find_batch_dir(batch_session_id)
    if not batch_dir:
        raise HTTPException(status_code=404, detail="Batch session not found")

    template_path = os.path.join(batch_dir, f"summary_template_{invoice_session_id}.csv")
    mapping_path = os.path.join(batch_dir, f"summary_mapping_{invoice_session_id}.json")
    filename_path = os.path.join(batch_dir, f"summary_template_filename_{invoice_session_id}.txt")

    has_template = os.path.isfile(template_path)
    has_mapping = os.path.isfile(mapping_path)
    columns = []
    template_filename = None

    if has_template:
        try:
            df = pd.read_csv(template_path, nrows=0)
            columns = list(df.columns)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as e:
            logger.warning("Could not read summary template columns: %s", e)
        if os.path.isfile(filename_path):
            try:
                with open(filename_path, "r", encoding="utf-8") as f:
                    template_filename = f.read().strip()
            except OSError as e:
                logger.warning("Could not read template filename: %s", e)

    mapping_obj = None
    if has_mapping:
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                mapping_obj = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Could not read summary mapping: %s", e)

    return {
        "has_template": has_template,
        "has_mapping": has_mapping,
        "columns": columns,
        "mapping": mapping_obj or {},
        "template_filename": template_filename,
    }


# ---------------------------------------------------------------------------
# Summary editor endpoints
# ---------------------------------------------------------------------------

@router.post("/api/generate-summary-data/{session_id}")
async def generate_summary_data(
    session_id: str,
    invoice_data_json: str = Form(None),
    current_user: str = Depends(require_auth),
):
    """Generate merged summary data (fresh rows + user edits overlay).

    Returns columns, rows, and the edited_cells mask so the frontend
    can continue tracking which cells are user-owned.
    """
    try:
        invoice_data_path, temp_dir = session_manager.find_invoice_data_with_dir(session_id)
        if not temp_dir or not invoice_data_path:
            raise HTTPException(status_code=404, detail="Session not found")

        if invoice_data_json:
            invoice_data = json.loads(invoice_data_json)
            with open(invoice_data_path, 'wb') as f:
                pickle.dump(invoice_data, f)
        else:
            with open(invoice_data_path, 'rb') as f:
                invoice_data = pickle.load(f)

        result = build_merged_summary(temp_dir, session_id, invoice_data)
        if result is None:
            raise HTTPException(
                status_code=400,
                detail="No summary template or column mapping found. Please upload a summary template and set the column mapping first."
            )

        summary_columns, rows, edited_cells = result

        tpl_name_path = os.path.join(temp_dir, f"summary_template_filename_{session_id}.txt")
        template_filename = None
        if os.path.isfile(tpl_name_path):
            with open(tpl_name_path, "r", encoding="utf-8") as fn:
                template_filename = fn.read().strip()

        src_fn_path = os.path.join(temp_dir, f"{session_id}_source_filename.txt")
        source_filename = None
        if os.path.isfile(src_fn_path):
            with open(src_fn_path, "r", encoding="utf-8") as fn:
                source_filename = fn.read().strip()

        return JSONResponse({
            "columns": summary_columns,
            "rows": rows,
            "edited_cells": edited_cells,
            "template_filename": template_filename,
            "source_filename": source_filename,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating summary data: {str(e)}")


@router.post("/api/save-summary-edits/{session_id}")
async def save_summary_edits(
    session_id: str,
    columns: str = Form(...),
    rows: str = Form(...),
    edited_cells: str = Form("[]"),
    current_user: str = Depends(require_auth),
):
    """Save edited summary CSV data and the edited-cells mask to disk.

    The mask records which cells were manually touched so that future
    regenerations can preserve them.
    """
    try:
        cols = json.loads(columns)
        row_data = json.loads(rows)
        mask = json.loads(edited_cells)

        _, temp_dir = session_manager.find_invoice_data_with_dir(session_id)
        if not temp_dir:
            raise HTTPException(status_code=404, detail="Session not found")

        out_df = pd.DataFrame(row_data, columns=cols)
        summary_csv_path = os.path.join(temp_dir, f"summary_single_{session_id}.csv")
        out_df.to_csv(summary_csv_path, index=False, encoding="utf-8")

        edits_mask_path = os.path.join(temp_dir, f"summary_edits_{session_id}.json")
        with open(edits_mask_path, "w", encoding="utf-8") as f:
            json.dump({"edited_cells": mask}, f)

        return JSONResponse({"ok": True})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving summary: {str(e)}")


@router.get("/api/download-summary-csv/{session_id}")
async def download_summary_csv(
    session_id: str,
    current_user: str = Depends(require_auth),
):
    """Download the saved summary CSV for a single invoice session."""
    _, temp_dir = session_manager.find_invoice_data_with_dir(session_id)
    if not temp_dir:
        raise HTTPException(status_code=404, detail="Session not found")

    summary_csv_path = os.path.join(temp_dir, f"summary_single_{session_id}.csv")
    if not os.path.isfile(summary_csv_path):
        raise HTTPException(status_code=404, detail="Summary CSV not found. Generate summary data first.")

    src_fn_path = os.path.join(temp_dir, f"{session_id}_source_filename.txt")
    if os.path.isfile(src_fn_path):
        with open(src_fn_path, "r", encoding="utf-8") as fn:
            invoice_stem = Path(fn.read().strip()).stem
    else:
        invoice_stem = session_id
    download_name = f"{invoice_stem}_backing_data.csv"

    return FileResponse(
        summary_csv_path,
        media_type="text/csv",
        filename=download_name,
    )


@router.get("/summary-editor", response_class=HTMLResponse)
async def summary_editor_page(request: Request, current_user: str = Depends(require_auth)):
    """Serve the in-browser summary CSV editor page."""
    return templates.TemplateResponse("summary_editor.html", {"request": request})
