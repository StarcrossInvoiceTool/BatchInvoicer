import logging
import os
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def xlsx_to_csv(xlsx_file_path, output_dir=None):
    """
    Convert each sheet in an xlsx file to a separate CSV file.
    
    Args:
        xlsx_file_path (str): Path to the input xlsx file
        output_dir (str, optional): Directory to save CSV files. 
                                   If None, saves in the same directory as the xlsx file.
    """
    # Validate input file exists
    if not os.path.exists(xlsx_file_path):
        raise FileNotFoundError(f"File not found: {xlsx_file_path}")
    
    # Get the base name of the xlsx file (without extension)
    base_name = Path(xlsx_file_path).stem
    
    # Set output directory - create a folder named after the xlsx file
    if output_dir is None:
        # Create a folder with the xlsx file name in the same directory as the xlsx file
        xlsx_dir = os.path.dirname(os.path.abspath(xlsx_file_path))
        output_dir = os.path.join(xlsx_dir, base_name)
    else:
        # If custom output directory is provided, still create a subfolder with the xlsx file name
        output_dir = os.path.join(output_dir, base_name)
    
    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        excel_file = pd.ExcelFile(xlsx_file_path)
        sheet_names = excel_file.sheet_names

        logger.info("Found %d sheet(s) in %s", len(sheet_names), xlsx_file_path)

        for sheet_name in sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)

            safe_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_')).strip()
            csv_filename = f"{base_name}_{safe_sheet_name}.csv"
            csv_path = os.path.join(output_dir, csv_filename)

            df.to_csv(csv_path, index=False, encoding='utf-8')
            logger.info("Created: %s (%d rows)", csv_path, len(df))

        logger.info("Conversion complete — %d CSV(s) in %s", len(sheet_names), output_dir)

    except (FileNotFoundError, ValueError, OSError) as e:
        raise ValueError(f"Error processing xlsx file: {str(e)}") from e


if __name__ == "__main__":
    # Get xlsx file path from command line argument or use default
    if len(sys.argv) > 1:
        xlsx_path = sys.argv[1]
    else:
        # Prompt user for file path if not provided
        xlsx_path = input("Enter the path to the xlsx file: ").strip().strip('"')
    
    # Optional: Get output directory from command line
    output_directory = None
    if len(sys.argv) > 2:
        output_directory = sys.argv[2]
    
    try:
        xlsx_to_csv(xlsx_path, output_directory)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

