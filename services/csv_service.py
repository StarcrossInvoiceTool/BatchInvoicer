"""CSV merge, collection, and per-file invoice-creation helpers."""

import json
import logging
import os
import pickle
import shutil
from typing import Optional

import pandas as pd
from fastapi import HTTPException

import session_manager

logger = logging.getLogger(__name__)
from csv_cleaner import csv_to_dataframe
from DataScraper import transform_dataframe_to_invoice_data
from services.invoice_service import serialize_invoice_data


def merge_csv_dataframes(csv_paths: list[str]) -> pd.DataFrame:
    """Read a list of CSV file paths and return a single concatenated DataFrame."""
    dataframes = []
    for path in csv_paths:
        try:
            dataframes.append(pd.read_csv(path))
        except (FileNotFoundError, pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error reading {os.path.basename(path)}: {e}",
            )
    if not dataframes:
        raise HTTPException(status_code=400, detail="No valid CSV data found")
    return pd.concat(dataframes, ignore_index=True)


def save_merged_csv(
    merged_df: pd.DataFrame,
    session_id: str,
    temp_dir: str,
    filename: Optional[str],
) -> dict:
    """Write *merged_df* into *temp_dir*/merged/ and return a response dict."""
    if filename:
        output_filename = filename.replace('.csv', '') + '.csv'
    else:
        output_filename = f"merged_{session_id[:8]}.csv"

    output_dir = os.path.join(temp_dir, "merged")
    os.makedirs(output_dir, exist_ok=True)
    merged_df.to_csv(os.path.join(output_dir, output_filename), index=False, encoding='utf-8')

    return {
        'session_id': session_id,
        'base_name': output_filename.replace('.csv', ''),
        'filename': output_filename,
        'file_count': 1,
        'files': [output_filename],
        'total_rows': len(merged_df),
    }


def collect_conversion_csvs(conversion_dir: str, files_filter: Optional[str] = None) -> list[str]:
    """Collect CSV file paths from a conversion directory, excluding the original upload."""
    original_file_path = None
    for item in os.listdir(conversion_dir):
        item_path = os.path.join(conversion_dir, item)
        if os.path.isfile(item_path) and item.endswith('.csv'):
            original_file_path = item_path
            break

    csv_files = []
    for root, _dirs, files_walk in os.walk(conversion_dir):
        for csv_file in files_walk:
            if csv_file.endswith('.csv'):
                file_path = os.path.join(root, csv_file)
                if file_path != original_file_path:
                    csv_files.append(file_path)

    if files_filter:
        try:
            selected = set(json.loads(files_filter))
            csv_files = [f for f in csv_files if os.path.basename(f) in selected]
        except (json.JSONDecodeError, TypeError):
            pass
    return csv_files


def process_csv_to_invoice(csv_path: str, batch_dir: str, index: int) -> dict:
    """Read a single CSV, convert to invoice data, persist artefacts, and return metadata."""
    df = csv_to_dataframe(csv_path)
    invoice_data = transform_dataframe_to_invoice_data(df)

    invoice_session_id = os.urandom(16).hex()
    invoice_data_path = os.path.join(batch_dir, f"{invoice_session_id}_invoice_data.pkl")
    source_csv_path = os.path.join(batch_dir, f"{invoice_session_id}_source.csv")

    with open(invoice_data_path, 'wb') as f:
        pickle.dump(invoice_data, f)

    shutil.copy2(csv_path, source_csv_path)
    csv_filename = os.path.basename(csv_path)
    with open(os.path.join(batch_dir, f"{invoice_session_id}_source_filename.txt"), "w", encoding="utf-8") as fn:
        fn.write(csv_filename)

    try:
        source_headers = list(pd.read_csv(source_csv_path, nrows=0).columns)
    except (OSError, pd.errors.ParserError):
        source_headers = list(df.columns)

    return {
        'session_id': invoice_session_id,
        'filename': csv_filename,
        'invoice_data': serialize_invoice_data(invoice_data),
        'source_headers': source_headers,
        'index': index,
    }
