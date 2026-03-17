import logging
import os
import pickle
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def csv_to_dataframe(csv_file_path):
    """
    Read a CSV file and convert it to a pandas DataFrame.
    Only keeps the specified columns in the DataFrame.
    
    Args:
        csv_file_path (str): Path to the input CSV file
    
    Returns:
        pd.DataFrame: The DataFrame containing only the specified columns
    """
    # Define the columns to keep
    columns_to_keep = [
        'Start Date',
        'Record ID',
        'Pas Number',
        'Passenger UPC',
        'Contract Hospital Text',
        'Caller',
        'From Postcode',
        'To Postcode',
        'Direction Text',
        'Jrny Status Text',
        'Actual Mileage',
        'Mobility Abbreviation',
        'Waiting Time Reason',
        'Forename',
        'Surname',
        'Patient Road',
        'Patient Town',
        'Patient Postcode',
        'Start Date range'
    ]
    
    # Validate input file exists
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"File not found: {csv_file_path}")
    
    try:
        df = pd.read_csv(csv_file_path)
        logger.info("Loaded CSV %s (%d rows, %d cols)", csv_file_path, *df.shape)

        existing_columns = [col for col in columns_to_keep if col in df.columns]
        missing_columns = [col for col in columns_to_keep if col not in df.columns]

        if missing_columns:
            logger.warning("Columns not found in CSV: %s", missing_columns)

        df = df[existing_columns]
        logger.debug("Filtered to %d rows, %d cols: %s", *df.shape, existing_columns)

        return df
    except (FileNotFoundError, pd.errors.ParserError, pd.errors.EmptyDataError, OSError) as e:
        raise ValueError(f"Error reading CSV file: {str(e)}") from e


if __name__ == "__main__":
    # Get CSV file path from command line argument or use default
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # Prompt user for file path if not provided
        csv_path = input("Enter the path to the CSV file: ").strip().strip('"')
    
    try:
        df = csv_to_dataframe(csv_path)
        print("\nDataFrame loaded successfully!")
        
        # Set pandas display options to show all rows and columns
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', None)
        
        print(f"\nAll data:\n{df}")
        
        # Save the dataframe to a pickle file for use in other scripts
        output_file = Path(csv_path).stem + "_cleaned.pkl"
        with open(output_file, 'wb') as f:
            pickle.dump(df, f)
        print(f"\nDataFrame saved to: {output_file}")
        print("You can load it in other files using: pd.read_pickle('{}')".format(output_file))
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
