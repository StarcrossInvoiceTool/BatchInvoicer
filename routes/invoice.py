"""Invoice routes: update, download, preview, and download-all."""

import json
import logging
import os
import pickle
import zipfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Form, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import config
import session_manager
from dependencies import require_auth
from models import parse_invoice_data

logger = logging.getLogger(__name__)
from services.invoice_service import (
    generate_invoice_html,
    format_date_word_format,
    format_date_dd_mm_yyyy,
    format_currency,
    _build_jinja_env,
)
from services.summary_service import (
    try_build_summary_zip,
    ensure_line_item_charges,
    build_summary_rows_from_line_items,
    build_merged_summary,
)

router = APIRouter()


@router.post("/api/update-invoice")
async def update_invoice(
    session_id: str = Form(...),
    invoice_data_json: str = Form(...),
    preview: str = Form("false"),
    current_user: str = Depends(require_auth),
):
    """Update invoice data and generate HTML.

    When preview=true, always return just the HTML (no ZIP with summary).
    """
    try:
        invoice_data = parse_invoice_data(invoice_data_json)
        is_preview = preview.lower() in ("true", "1", "yes")

        invoice_data_path, temp_dir = session_manager.find_invoice_data_with_dir(session_id)
        if not invoice_data_path or not temp_dir:
            raise HTTPException(status_code=404, detail="Session not found")

        with open(invoice_data_path, 'wb') as f:
            pickle.dump(invoice_data, f)

        html_file = generate_invoice_html(invoice_data_path, template_name=None)

        if not is_preview:
            try:
                result = build_merged_summary(temp_dir, session_id, invoice_data)
                if result is not None:
                    summary_columns, merged_rows, _ = result
                    if merged_rows:
                        out_df = pd.DataFrame(merged_rows, columns=summary_columns)
                        summary_csv_path = os.path.join(temp_dir, f"summary_single_{session_id}.csv")
                        out_df.to_csv(summary_csv_path, index=False, encoding="utf-8")
                        src_fn_path = os.path.join(temp_dir, f"{session_id}_source_filename.txt")
                        if os.path.isfile(src_fn_path):
                            with open(src_fn_path, "r", encoding="utf-8") as fn:
                                invoice_stem = Path(fn.read().strip()).stem
                        else:
                            invoice_stem = Path(html_file).stem
                        backing_name = f"{invoice_stem}_backing_data.csv"
                        zip_path = os.path.join(temp_dir, f"invoice_and_summary_{session_id}.zip")
                        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                            zipf.write(html_file, Path(html_file).name)
                            zipf.write(summary_csv_path, backing_name)
                        return FileResponse(
                            zip_path,
                            media_type="application/zip",
                            filename=f"invoice_and_summary_{Path(html_file).stem}.zip",
                        )
            except (OSError, ValueError, KeyError) as summary_err:
                logger.exception("Summary build failed: %s", summary_err)

        return FileResponse(html_file, media_type="text/html", filename=Path(html_file).name)
    except HTTPException:
        raise
    except (FileNotFoundError, pickle.UnpicklingError, OSError) as e:
        logger.exception("Error generating invoice")
        raise HTTPException(status_code=500, detail=f"Error generating invoice: {str(e)}")
    except Exception as e:
        logger.exception("Unexpected error generating invoice")
        raise HTTPException(status_code=500, detail=f"Error generating invoice: {str(e)}")


@router.post("/api/download-invoice/{session_id}")
async def download_invoice(session_id: str, current_user: str = Depends(require_auth)):
    """Download a single invoice HTML file."""
    try:
        invoice_data_path = session_manager.find_invoice_data_path(session_id)
        if not invoice_data_path:
            raise HTTPException(status_code=404, detail="Invoice not found")

        html_file = generate_invoice_html(invoice_data_path, template_name=None)
        return FileResponse(html_file, media_type="text/html", filename=Path(html_file).name)
    except HTTPException:
        raise
    except (FileNotFoundError, pickle.UnpicklingError, OSError) as e:
        logger.exception("Error downloading invoice %s", session_id)
        raise HTTPException(status_code=500, detail=f"Error downloading invoice: {str(e)}")


@router.post("/api/download-all-invoices")
async def download_all_invoices(
    batch_session_id: str = Form(...),
    current_user: str = Depends(require_auth),
):
    """Download all invoices from a batch session as a ZIP file.

    If a summary template and mapping exist, a filled summary CSV is included.
    """
    try:
        batch_dir, invoice_files = session_manager.find_batch_invoice_files(batch_session_id)
        if not batch_dir or not invoice_files:
            raise HTTPException(status_code=404, detail="Batch session not found")

        html_files = []
        for invoice_data_path in invoice_files:
            html_file = generate_invoice_html(invoice_data_path, template_name=None)
            html_files.append(html_file)

        zip_path = os.path.join(batch_dir, f"invoices_{batch_session_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for idx, html_file in enumerate(html_files):
                zipf.write(html_file, Path(html_file).name)
                invoice_data_path = invoice_files[idx]
                sid = Path(invoice_data_path).stem.replace("_invoice_data", "")
                template_path = os.path.join(batch_dir, f"summary_template_{sid}.csv")
                mapping_path = os.path.join(batch_dir, f"summary_mapping_{sid}.json")
                if os.path.isfile(template_path) and os.path.isfile(mapping_path):
                    with open(invoice_data_path, "rb") as f:
                        inv_data = pickle.load(f)
                    result = build_merged_summary(batch_dir, sid, inv_data)
                    if result is not None:
                        summary_columns, merged_rows, _ = result
                        if merged_rows:
                            out_df = pd.DataFrame(merged_rows, columns=summary_columns)
                            summary_csv_path = os.path.join(batch_dir, f"summary_single_{sid}_zip.csv")
                            out_df.to_csv(summary_csv_path, index=False, encoding="utf-8")
                            src_fn_path = os.path.join(batch_dir, f"{sid}_source_filename.txt")
                            if os.path.isfile(src_fn_path):
                                with open(src_fn_path, "r", encoding="utf-8") as fn:
                                    invoice_stem = Path(fn.read().strip()).stem
                            else:
                                invoice_stem = sid
                            zipf.write(summary_csv_path, f"{invoice_stem}_backing_data.csv")
                            try:
                                os.remove(summary_csv_path)
                            except OSError:
                                pass

        return FileResponse(zip_path, media_type="application/zip", filename=f"invoices_{batch_session_id}.zip")
    except HTTPException:
        raise
    except (FileNotFoundError, pickle.UnpicklingError, OSError, zipfile.BadZipFile) as e:
        logger.exception("Error creating invoice ZIP for batch %s", batch_session_id)
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(e)}")


@router.get("/api/invoice-preview/{session_id}")
async def invoice_preview(session_id: str, current_user: str = Depends(require_auth)):
    """Preview the invoice HTML for a session."""
    invoice_data_path = session_manager.find_invoice_data_path(session_id)
    if not invoice_data_path:
        raise HTTPException(status_code=404, detail="Session not found")

    with open(invoice_data_path, 'rb') as f:
        invoice_data = pickle.load(f)

    style = invoice_data.get('style', config.DEFAULT_INVOICE_STYLE)
    template_name = config.INVOICE_TEMPLATE_STYLE2 if style == 'style2' else config.INVOICE_TEMPLATE_STYLE1

    env = _build_jinja_env()
    template = env.get_template(template_name)
    html_content = template.render(data=invoice_data)
    return HTMLResponse(content=html_content)
