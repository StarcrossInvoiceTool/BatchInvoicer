import pandas as pd
import os
import re

def sanitize_filename(filename):
    """Remove or replace invalid filename characters"""
    # Replace invalid characters with underscore
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing spaces and dots
    filename = filename.strip(' .')
    # Replace multiple spaces/underscores with single underscore
    filename = re.sub(r'[\s_]+', '_', filename)
    return filename

def split_csv_by_budget_code(input_file, output_dir='output'):
    """
    Split a CSV file into multiple CSV files based on BudgetCodeText column.
    Each unique BudgetCodeText value gets its own CSV file.
    Special case: BARTS_BHOC_HDU and BARTS_HDU are combined into one file.
    """
    # Define budget codes that should be combined into one file
    # Format: {group_name: [list of budget codes to combine]}
    # Note: Use the exact values as they appear in the CSV
    combined_groups = {
        'BARTS_HDU': ['BARTS BHOC HDU', 'BARTS HDU']
    }
    
    # Create a reverse mapping: budget_code -> group_name
    budget_code_to_group = {}
    for group_name, codes in combined_groups.items():
        for code in codes:
            budget_code_to_group[code] = group_name
    
    # Read the CSV file
    print(f"Reading CSV file: {input_file}")
    df = pd.read_csv(input_file)
    
    # Check if BudgetCodeText column exists
    if 'BudgetCodeText' not in df.columns:
        raise ValueError("Column 'BudgetCodeText' not found in the CSV file")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Get unique BudgetCodeText values
    unique_budget_codes = df['BudgetCodeText'].unique()
    print(f"Found {len(unique_budget_codes)} unique BudgetCodeText values")
    
    # Track which groups have been processed
    processed_groups = set()
    
    # Group by BudgetCodeText and create separate CSV files
    for budget_code in unique_budget_codes:
        # Check if this budget code belongs to a combined group
        if budget_code in budget_code_to_group:
            group_name = budget_code_to_group[budget_code]
            
            # Skip if we've already processed this group
            if group_name in processed_groups:
                continue
            
            # Mark this group as processed
            processed_groups.add(group_name)
            
            # Get all budget codes in this group
            codes_to_combine = combined_groups[group_name]
            
            # Filter rows for all codes in this group
            filtered_df = df[df['BudgetCodeText'].isin(codes_to_combine)]
            
            # Create safe filename
            safe_name = sanitize_filename(group_name)
            filename = f"{safe_name}.csv"
        else:
            # Regular processing for non-combined codes
            # Filter rows for this budget code
            filtered_df = df[df['BudgetCodeText'] == budget_code]
            
            # Create safe filename
            if pd.isna(budget_code) or budget_code == '':
                filename = 'No_BudgetCode.csv'
            else:
                safe_name = sanitize_filename(str(budget_code))
                filename = f"{safe_name}.csv"
        
        output_path = os.path.join(output_dir, filename)
        
        # Write to CSV
        filtered_df.to_csv(output_path, index=False)
        print(f"Created: {output_path} ({len(filtered_df)} rows)")
    
    print(f"\nAll files created in '{output_dir}' directory")

if __name__ == "__main__":
    # Default input file name
    input_file = "Cleric Data All WE-07-12-2025.csv"
    
    # Check if file exists
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found!")
        print("Please make sure the CSV file is in the same directory as this script.")
    else:
        split_csv_by_budget_code(input_file)

