import pandas as pd
import sys
import os
from pathlib import Path


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
    
    # Read all sheets from the xlsx file
    try:
        excel_file = pd.ExcelFile(xlsx_file_path)
        sheet_names = excel_file.sheet_names
        
        print(f"Found {len(sheet_names)} sheet(s) in {xlsx_file_path}")
        
        # Convert each sheet to CSV
        for sheet_name in sheet_names:
            # Read the sheet
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            
            # Create CSV filename (sanitize sheet name for filename)
            safe_sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '-', '_')).strip()
            csv_filename = f"{base_name}_{safe_sheet_name}.csv"
            csv_path = os.path.join(output_dir, csv_filename)
            
            # Save to CSV
            df.to_csv(csv_path, index=False, encoding='utf-8')
            print(f"Created: {csv_path} ({len(df)} rows)")
        
        print(f"\nConversion complete! {len(sheet_names)} CSV file(s) created in {output_dir}")
        
    except Exception as e:
        raise Exception(f"Error processing xlsx file: {str(e)}")


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

