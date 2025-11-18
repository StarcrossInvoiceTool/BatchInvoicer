import pandas as pd
import pickle
import sys
import os
from pathlib import Path


def load_cleaned_dataframe(pkl_file_path):
    """
    Load a cleaned DataFrame from a pickle file.
    
    Args:
        pkl_file_path (str): Path to the pickle file
    
    Returns:
        pd.DataFrame: The loaded DataFrame
    """
    if not os.path.exists(pkl_file_path):
        raise FileNotFoundError(f"Pickle file not found: {pkl_file_path}")
    
    try:
        df = pd.read_pickle(pkl_file_path)
        print(f"Successfully loaded DataFrame from: {pkl_file_path}")
        print(f"DataFrame shape: {df.shape[0]} rows, {df.shape[1]} columns")
        return df
    except Exception as e:
        raise Exception(f"Error loading pickle file: {str(e)}")


def clean_value(value):
    """
    Clean a value from DataFrame, handling NaN and empty values.
    Returns empty string if value is NaN, None, or empty.
    Removes ".0" suffix from numeric values.
    """
    if pd.isna(value) or value is None or str(value).strip() == '' or str(value).lower() == 'nan':
        return ''
    
    # Convert to string and strip whitespace
    value_str = str(value).strip()
    
    # Remove ".0" suffix if present (handles float values like "123.0")
    if value_str.endswith('.0'):
        value_str = value_str[:-2]
    
    return value_str


def get_column_value(row, possible_names):
    """
    Get a value from a row trying multiple possible column names.
    Returns the first value found (even if empty), or empty string if none found.
    """
    for name in possible_names:
        if name in row.index:
            return row.get(name, '')
    return ''


def transform_dataframe_to_invoice_data(df):
    """
    Transform the cleaned DataFrame into the invoice data structure.
    
    Args:
        df (pd.DataFrame): The cleaned DataFrame from csv_cleaner
    
    Returns:
        dict: Invoice data structure matching the template requirements
    """
    if df.empty:
        raise ValueError("DataFrame is empty")
    
    # Debug: Print available columns to help troubleshoot
    print(f"Available columns in DataFrame: {list(df.columns)}")
    
    # Get patient information from the first row
    # Combine Forename and Surname for patient name
    first_row = df.iloc[0]
    patient_name = f"{first_row.get('Forename', '')} {first_row.get('Surname', '')}".strip()
    
    # Combine Patient Road and Patient Town for patient address
    patient_road = str(first_row.get('Patient Road', '')).strip()
    patient_town = str(first_row.get('Patient Town', '')).strip()
    patient_address = f"{patient_road}, {patient_town}".strip(', ')
    
    patient_postcode = str(first_row.get('Patient Postcode', '')).strip()
    
    # Transform each row into an invoice item
    invoice_items = []
    for _, row in df.iterrows():
        # Get date and our_ref, cleaning them
        date_value = str(row.get('Start Date', '')).strip()
        our_ref_value = clean_value(row.get('Record ID', ''))
        
        # Check if both date and our_ref are 'nan' or empty - if so, skip this item
        date_is_nan = (date_value.lower() == 'nan' or date_value == '' or pd.isna(row.get('Start Date', '')))
        ref_is_nan = (our_ref_value.lower() == 'nan' or our_ref_value == '' or pd.isna(row.get('Record ID', '')))
        
        if date_is_nan and ref_is_nan:
            continue  # Skip this item
        
        item = {
            'date': date_value,
            'our_ref': our_ref_value,  # Already cleaned (removes .0 suffix)
            'client_ref': clean_value(row.get('Pas Number', '')),
            'nhs_number': clean_value(get_column_value(row, ['Passenger UPC', 'PassengerUPC', 'Passenger UPC Code'])),
            'contract_hospital': str(row.get('Contract Hospital Text', '')),
            'booked_by': clean_value(row.get('Caller', '')),
            'from_location': str(row.get('From Postcode', '')),
            'to_location': str(row.get('To Postcode', '')),
            'status': str(row.get('Jrny Status Text', '')),
            'directions': str(row.get('Direction Text', '')),
            'mob': clean_value(row.get('Mobility Abbreviation', '')),
            'wait_pounds': '',  # Financial field, to be filled later
            'wait_notes': str(row.get('Waiting Time Reason', '')),
            'miles': str(row.get('Actual Mileage', '')),
            'charged': '',  # Not in source data, left empty
            'miles_pounds': '',  # Financial field, to be filled later
            'job_pounds': '',  # Financial field, to be filled later
            'total': ''  # Financial field, to be filled later
        }
        invoice_items.append(item)
    
    # Create the invoice data structure
    invoice_data = {
        'patient': {
            'name': patient_name,
            'address': patient_address,
            'postcode': patient_postcode
        },
        'invoice': {
            'number': '',  # To be filled via UI
            'date': '',  # To be filled via UI
            'account_ref': '',  # To be filled via UI
            'ref': '',  # To be filled via UI
            'po_number': '',  # To be filled via UI
            'payment_terms': '',  # To be filled via UI
            'period': '',  # To be filled via UI
            'items': invoice_items
        },
        'financial': {
            'net': '',  # To be filled via UI
            'net_label': 'net',  # Editable label
            'discount': '',  # To be filled via UI
            'discount_label': 'discount',  # Editable label
            'subtotal': '',  # To be filled via UI
            'subtotal_label': 'Invoice subtotal',  # Editable label
            'vat_amount': '',  # To be filled via UI
            'vat_label': 'VAT 20%',  # Editable label
            'total': '',  # To be filled via UI
            'total_label': 'TOTAL DUE'  # Editable label
        },
        'bank': {
            'name': 'Lloyds Bank Plc',
            'account_name': 'Starcross Trading Limited',
            'account_number': '82082760',
            'sort_code': '30-99-21'
        }
    }
    
    return invoice_data


def process_pickle_to_invoice_data(pkl_file_path):
    """
    Main function to load pickle file and transform to invoice data structure.
    
    Args:
        pkl_file_path (str): Path to the pickle file
    
    Returns:
        dict: Invoice data structure ready for template rendering
    """
    df = load_cleaned_dataframe(pkl_file_path)
    invoice_data = transform_dataframe_to_invoice_data(df)
    return invoice_data


if __name__ == "__main__":
    # Get pickle file path from command line argument or use default
    if len(sys.argv) > 1:
        pkl_path = sys.argv[1]
    else:
        # Prompt user for file path if not provided
        pkl_path = input("Enter the path to the pickle file: ").strip().strip('"')
    
    try:
        invoice_data = process_pickle_to_invoice_data(pkl_path)
        print("\nInvoice data structure created successfully!")
        print(f"\nPatient Name: {invoice_data['patient']['name']}")
        print(f"Patient Address: {invoice_data['patient']['address']}")
        print(f"Patient Postcode: {invoice_data['patient']['postcode']}")
        print(f"\nNumber of invoice items: {len(invoice_data['invoice']['items'])}")
        print("\nFirst invoice item:")
        if invoice_data['invoice']['items']:
            first_item = invoice_data['invoice']['items'][0]
            for key, value in first_item.items():
                print(f"  {key}: {value}")
        
        # Save the invoice data to a pickle file for use in HTML generation
        output_file = Path(pkl_path).stem + "_invoice_data.pkl"
        with open(output_file, 'wb') as f:
            pickle.dump(invoice_data, f)
        print(f"\nInvoice data saved to: {output_file}")
        print("You can load it in other files using: pickle.load(open('{}', 'rb'))".format(output_file))
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

