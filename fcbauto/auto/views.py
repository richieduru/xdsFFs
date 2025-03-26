import os
import pandas as pd
import re
import dateparser
import numpy as np
from datetime import datetime, timedelta
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.shortcuts import render
from .forms import ExcelUploadForm
from .map import consu_mapping, comm_mapping, guar_mapping, credit_mapping, prin_mapping,Gender_dict,Country_dict,state_dict,Marital_dict,Borrower_dict,Employer_dict,Title_dict,Occu_dict,AccountStatus_dict,Loan_dict,Repayment_dict,Currency_dict,Classification_dict,Collateraltype_dict,ConsuToComm
from rapidfuzz import fuzz, process
from typing import Union, Optional
from word2number import w2n  
from datetime import datetime
import traceback
import json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import uuid

def create_empty_sheet(mapping_dict):
    """
    Create an empty DataFrame with columns from the mapping dictionary
    """
    columns = list(mapping_dict.keys())
    return pd.DataFrame(columns=columns)

def ensure_all_sheets_exist(xds):
    """
    Check for missing sheets and create them with appropriate headers if needed
    """
    # Define expected sheets and their corresponding mappings
    expected_sheets = {
        'individualborrowertemplate': consu_mapping,
        'corporateborrowertemplate': comm_mapping,
        'creditinformation': credit_mapping,
        'guarantorsinformation': guar_mapping,
        'principalofficerstemplate': prin_mapping
    }
    
    processed_sheets = {}
    missing_sheets = []
    existing_sheets = []
    
    print("\n=== SHEET PROCESSING REPORT ===")
    print("Checking for required sheets...")
    
    for sheet_name, mapping in expected_sheets.items():
        # Clean the sheet name for comparison
        cleaned_name = clean_sheet_name(sheet_name)
        
        # Check if sheet exists in uploaded file
        sheet_exists = False
        for original_name in xds.keys():
            if clean_sheet_name(original_name) == cleaned_name:
                print(f"? Found existing sheet: {original_name}")
                processed_sheets[cleaned_name] = xds[original_name]
                sheet_exists = True
                existing_sheets.append(sheet_name)
                break
        
        # If sheet doesn't exist, create it
        if not sheet_exists:
            print(f"? Missing sheet detected: {sheet_name}")
            print(f"? Generating new sheet: {sheet_name}")
            print(f"  - Adding {len(mapping)} columns based on template")
            processed_sheets[cleaned_name] = create_empty_sheet(mapping)
            missing_sheets.append(sheet_name)
    
    # Summary report
    print("\n=== SHEET GENERATION SUMMARY ===")
    print(f"Total sheets required: {len(expected_sheets)}")
    print(f"Sheets found in upload: {len(existing_sheets)}")
    print(f"Sheets auto-generated: {len(missing_sheets)}")
    
    if missing_sheets:
        print("\nAuto-generated sheets:")
        for sheet in missing_sheets:
            print(f"- {sheet}")
    
    print("\n=============================")
    
    return processed_sheets


def clean_sheet_name(sheet_name):
    """Clean sheet names by removing special characters"""
    cleaned_name = re.sub(r'[^a-zA-Z0-9]', '', sheet_name)  
    return cleaned_name.lower()

def remove_special_characters(column_name):
    """Remove special characters and all spaces from column names"""
    # Remove non-alphanumeric characters but allow spaces
    pattern = r'[^a-zA-Z0-9]'  # Remove special characters
    cleaned_name = re.sub(pattern, '', column_name)  # Remove special characters
    
    # Remove all spaces
    cleaned_name = cleaned_name.replace(' ', '')  # Remove all spaces
    
    return cleaned_name

def remove_special_chars(text):
    """Remove special characters from text while preserving spaces"""
    if pd.isna(text) or text is None:  # Handle NaN and None values
        return ''
    if not isinstance(text, str):
        text = str(text)
    
    # Remove special characters but keep spaces
    cleaned = re.sub(r'[^a-zA-Z\s]', '', text)
    
    # Replace multiple spaces with single space and trim
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned

def remove_titles(name):
    """Remove common titles from names"""
    if not isinstance(name, str):
        return name
        
    titles = ['Miss', 'Mrs', 'Rev', 'Dr', 'Mr', 'MS', 'CAPT', 
              'COL', 'LADY', 'MAJ', 'PST', 'PROF', 'REV', 'SGT',
              'SIR', 'HE', 'JUDG', 'CHF', 'ALHJ', 'APOS', 'CDR','ALH','Alh',
              'BISH', 'FLT', 'BARR', 'MGEN', 'GEN', 'HON', 'ENGR', 'LT']
    
    pattern = r'\b(?:' + '|'.join(re.escape(title) for title in titles) + r')\b'
    cleaned_name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    return ' '.join(cleaned_name.split())


def remove_duplicate_columns(df):
    """
    Remove duplicate columns, keeping first occurrence
    
    Args:
        df (pd.DataFrame): Input DataFrame
    
    Returns:
        pd.DataFrame: DataFrame with unique columns
    """
    if df is None or df.empty:
        return df
    
    # Identify unique columns
    unique_columns = []
    duplicate_columns = []  # To keep track of duplicates
    for col in df.columns:
        if col not in unique_columns:
            unique_columns.append(col)
        else:
            duplicate_columns.append(col)  # Track duplicates
    
    # Create DataFrame with unique columns
    df_cleaned = df[unique_columns]
    
    # Log column removals
    columns_removed = len(df.columns) - len(unique_columns)
    if columns_removed > 0:
        print(f"Removed {columns_removed} duplicate columns: {duplicate_columns}")
    
    return df_cleaned

def convert_date(date_string):
    """Converts a date string or Excel serial number to the specified format (YYYYMMDD), 
    or returns None for empty/invalid rows.
    
    Args:
        date_string: A string or number representing a date.
        
    Returns:
        A string representing the date in the specified format (YYYYMMDD), or None for empty or invalid dates.
    """
    # Check if the cell is empty or None
    if date_string is None or (isinstance(date_string, float) and np.isnan(date_string)):
        return None

    # Define common missing value representations
    missing_values = ["", "None", "NaN", "null", "N/A", "n/a", "na", "NA", "#N/A", "?", "missing"]
    
    # Check if the cell is a missing value
    if isinstance(date_string, str) and date_string.strip() in missing_values:
        return None
        
    # Check if the date is already in YYYYMMDD format
    if isinstance(date_string, str):
        # Remove any whitespace
        clean_date = date_string.strip()
        # Check if it's already in YYYYMMDD format (8 digits with no separators)
        if re.match(r'^\d{8}$', clean_date):
            # Validate that it's a valid date
            try:
                year = int(clean_date[:4])
                month = int(clean_date[4:6])
                day = int(clean_date[6:8])
                # Basic validation
                if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                    return clean_date  # Already in the correct format
            except (ValueError, IndexError):
                pass  # Not a valid YYYYMMDD date, continue with conversion

    # Check if the input is a number (e.g., Excel serial number)
    try:
        serial_number = float(date_string)
        
        # Check if the serial number is within the valid Excel date range
        if serial_number < 0 or serial_number > 2958465:
            return None  # Invalid range for Excel date serial numbers
        
        # Excel serial date base is 1899-12-30
        base_date = datetime(1899, 12, 30)
        calculated_date = base_date + timedelta(days=int(serial_number))
        return f"{calculated_date.year:04d}{calculated_date.month:02d}{calculated_date.day:02d}"
    except (ValueError, TypeError):
        # If not a valid number, proceed with parsing as a string
        pass

    # Define date formats with explicit separation between 2-digit and 4-digit year formats
    two_digit_year_formats = [
        '%d/%m/%y', '%m/%d/%y', '%y/%m/%d',  # Two-digit year formats with slashes
        '%d-%m-%y', '%m-%d-%y', '%y-%m-%d',  # Two-digit year formats with hyphens
        '%d.%m.%y', '%m.%d.%y', '%y.%m.%d',  # Two-digit year formats with dots
    ]
    
    four_digit_year_formats = [
        '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d',  # Four-digit year formats with slashes
        '%d-%m-%Y', '%m-%d-%Y', '%Y-%m-%d',  # Four-digit year formats with hyphens
        '%d.%m.%Y', '%m.%d.%Y', '%Y.%m.%d',  # Four-digit year formats with dots
        '%Y%m%d', '%d%m%Y', '%m%d%Y'         # Four-digit year formats without separators
    ]
    
    # First try with four-digit year formats
    for fmt in four_digit_year_formats:
        try:
            date = datetime.strptime(str(date_string).strip(), fmt)
            return f"{date.year:04d}{date.month:02d}{date.day:02d}"
        except ValueError:
            continue
    
    # Then try with two-digit year formats and apply the sliding window
    for fmt in two_digit_year_formats:
        try:
            date = datetime.strptime(str(date_string).strip(), fmt)
            
            # Apply Excel's sliding window logic for two-digit years
            two_digit_year = date.year % 100
            if 0 <= two_digit_year <= 29:
                adjusted_year = 2000 + two_digit_year
            else:
                adjusted_year = 1900 + two_digit_year
            
            # Replace the year while keeping month/day the same
            date = date.replace(year=adjusted_year)
            return f"{date.year:04d}{date.month:02d}{date.day:02d}"
        except ValueError:
            continue
    
    # If all explicit formats fail, try dateparser as a fallback
    try:
        date = dateparser.parse(str(date_string))
        if date:
            return f"{date.year:04d}{date.month:02d}{date.day:02d}"
    except:
        pass
        
    return None

        
def process_dates(df):
    """Process date fields in the DataFrame"""
    date_columns = [
        'DATEOFBIRTH',
        'DATEOFINCORPORATION',
        'PRINCIPALOFFICER1DATEOFBIRTH',
        'PRINCIPALOFFICER2DATEOFBIRTH',
        'SPOUSEDATEOFBIRTH',
        'GUARANTORDATEOFBIRTHINCORPORATION',
        'LOANEFFECTIVEDATE',
        'MATURITYDATE',
        'LASTPAYMENTDATE',
        'DEFEREDPAYMENTDATE',
        'LITIGATIONDATE',
        'ACCOUNTSTATUSDATE'
    ]
    
    for col in df.columns:
        # Check if column name contains 'date' (case insensitive)
        if 'date' in col.lower() or col in date_columns:
            print(f"Processing date column: {col}")  # Debug print
            try:
                df[col] = df[col].apply(convert_date)
                # Print sample of converted dates
                print(f"Sample of converted dates for {col}:")
                print(df[col].head())
            except Exception as e:
                print(f"Error processing dates in column {col}: {str(e)}")
    
    return df

def remove_titles(name):
    """Remove common titles from names"""
    if not isinstance(name, str):
        return ''
    
    titles = ['Miss', 'Mrs', 'Rev', 'Dr', 'Mr', 'MS', 'CAPT', 
              'COL', 'LADY', 'MAJ', 'PST', 'PROF', 'REV', 'SGT',
              'SIR', 'HE', 'JUDG', 'CHF', 'ALHJ', 'APOS', 'CDR',
              'BISH', 'FLT', 'BARR', 'MGEN', 'GEN', 'HON', 'ENGR', 'LT']
    
    pattern = r'\b(?:' + '|'.join(re.escape(title) for title in titles) + r')\b'
    cleaned_name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    return ' '.join(cleaned_name.split())

def remove_special_chars(text):
    """Remove special characters from text while preserving spaces"""
    if not text:
        return ''
    
    # Convert to string if not already
    text = str(text)
    # Replace common punctuation with spaces
    text = re.sub(r'[.,\'"\-_/\\|&]', ' ', text)
    # Remove any remaining special characters but keep spaces
    text = re.sub(r'[^a-zA-Z\s]', '', text)
    # Replace multiple spaces with single space and strip
    text = ' '.join(text.split())
    
    return text.strip()

def process_names(df):
    """Process names before column mapping"""
    if df is None or df.empty:
        return df
        
    name_groups = {
        'primary': ['SURNAME', 'FIRSTNAME', 'MIDDLENAME'],
        'spouse': ['SPOUSESURNAME', 'SPOUSEFIRSTNAME', 'SPOUSEMIDDLENAME'],
        'principal1': ['PRINCIPALOFFICER1SURNAME', 'PRINCIPALOFFICER1FIRSTNAME', 'PRINCIPALOFFICER1MIDDLENAME'],
        'principal2': ['PRINCIPALOFFICER2SURNAME', 'PRINCIPALOFFICER2FIRSTNAME', 'PRINCIPALOFFICER2MIDDLENAME'],
        'guarantor': ['INDIVIDUALGUARANTORSURNAME', 'INDIVIDUALGUARANTORFIRSTNAME', 'INDIVIDUALGUARNTORMIDDLENAME']
    }
    
    for group_name, name_columns in name_groups.items():
        if all(col in df.columns for col in name_columns):
            # Debug print
            print(f"\nProcessing group: {group_name}")
            print("Original columns:", df[name_columns].head())
            
            # Explicitly clean columns
            for col in name_columns:
                # Convert to string, replace NaN with empty string
                df[col] = df[col].apply(lambda x: '' if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip())
            
            # Print after initial cleaning
            print("After initial cleaning:", df[name_columns].head())
            
            # Remove titles and special characters
            for col in name_columns:
                df[col] = df[col].apply(remove_titles).apply(remove_special_chars)
            
            # Combine non-empty name components
            def combine_names(row):
                # Filter out empty strings before joining
                name_components = [
                    row[name_columns[0]], 
                    row[name_columns[1]], 
                    row[name_columns[2]]
                ]
                # Remove empty strings
                name_components = [comp for comp in name_components if comp]
                
                # Join non-empty components
                return ' '.join(name_components)
            
            temp_full_name = f'FULL_NAME_{group_name}'
            df[temp_full_name] = df.apply(combine_names, axis=1)
            
            # Print combined names
            print("Combined names:", df[temp_full_name].head())
            
            # Split the full name back into components
            name_parts = df[temp_full_name].apply(lambda x: pd.Series(x.split(maxsplit=2) + ['', '', ''])[:3])
            
            # Update original columns with processed parts
            df[name_columns[0]] = name_parts[0]
            df[name_columns[1]] = name_parts[1]
            df[name_columns[2]] = name_parts[2]
            
            # Print final processed columns
            print("Final processed columns:", df[name_columns].head())
            
            # Drop the temporary column
            df = df.drop(temp_full_name, axis=1)
        else:
            # Process individual columns if the full group is not present
            for col in name_columns:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: '' if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip())
                    df[col] = df[col].apply(remove_titles).apply(remove_special_chars)
    
    return df

def rename_columns_with_fuzzy_rapidfuzz(df, mapping, threshold=90):
    def fuzzy_match(column, alt_names):
        result = process.extractOne(column, alt_names, scorer=fuzz.token_set_ratio)
        if result and result[1] >= threshold:
            return result[0]
        return None

    # Track renamed columns to avoid conflicts
    renamed_columns = set()

    # Create a mapping to track which keys have been used
    used_keys_mapping = {key: None for key in mapping}

    # Iterate over the columns and rename them
    for column in df.columns:
        found_match = False
        for mapped_column, alt_names in mapping.items():
            # Check if the key has been used
            if used_keys_mapping[mapped_column] is not None:
                continue

            # Check if the column name is in alt_names
            if column.lower() in alt_names or column.upper() in alt_names or column == mapped_column:
                df.rename(columns={column: mapped_column}, inplace=True)
                renamed_columns.add(mapped_column)
                used_keys_mapping[mapped_column] = column
                print(f"Renamed {column} to {mapped_column}")
                found_match = True
                break

        # If no exact match found, try fuzzy matching
        if not found_match:
            fuzzy_match_result = fuzzy_match(column, mapping.keys())
            if fuzzy_match_result:
                # Check if the key has been used
                if used_keys_mapping[fuzzy_match_result] is None:
                    df.rename(columns={column: fuzzy_match_result}, inplace=True)
                    renamed_columns.add(fuzzy_match_result)
                    used_keys_mapping[fuzzy_match_result] = column
                    print(f"Fuzzy matched {column} to {fuzzy_match_result}")
                else:
                    # Drop the column if a fuzzy match has already been used
                    df.drop(columns=[column], inplace=True)
                    print(f"Column {column} dropped due to key conflict.")

    # Drop duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]

    # Add columns for keys that were not mapped
    new_columns = {key: None for key, used_column in used_keys_mapping.items() if used_column is None}
    df = pd.concat([df, pd.DataFrame(new_columns, index=df.index)], axis=1)

    # Reorder the columns based on the keys in the dictionary
    df = df[list(mapping.keys())]

    return df
def fill_data_column(df):
    """
    Fill the 'DATA' column with 'D' after column renaming
    """
    if 'DATA' in df.columns:
        df['DATA'] = 'D'
    else:
        print("===========================")
    return df

def fill_depend_column(df):
    """
    Fill the 'DEPENDANTS' column with '00' after column renaming
    """
    if 'DEPENDANTS' in df.columns:
        df['DEPENDANTS'] = df['DEPENDANTS'].apply(lambda x: '00' if pd.isna(x) or str(x).strip() in ['', 'None', 'nan', 'null', 'nill', 'nil', 'na', 'n/a'] else x)
    else:
        print("\n=== DEPENDANTS COLUMN NOT FOUND ===") 
    return df

def process_gender(df):
    """Process gender fields in the DataFrame"""
    gender_columns = [
        'GENDER',
        'SPOUSEGENDER',
        'PRINCIPALOFFICER1GENDER',
        'PRINCIPALOFFICER2GENDER',
        'GUARANTORGENDER',
        'INDIVIDUALGUARANTORGENDER'
    ]
    
    for col in gender_columns:
        if col in df.columns:
            try:
                # Check if the column has any non-null values before processing
                if df[col].notna().any():
                    df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
                    df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
                    df[col] = df[col].apply(map_gender)
                else:
                    print(f"No non-null values found in column '{col}'.")
            except Exception as e:
                print(f"Error processing column '{col}': {e}")
    return df

def map_gender(value):
    """Maps gender values to standardized format"""
    if isinstance(value, pd.Series):  # Handle Series input
        return value.apply(map_gender)
    
    if pd.isna(value) or value is None:
        return None

    if not isinstance(value, str):
        value = str(value)

    value = value.lower().strip()
    
    if value in ['', 'none', 'nan', 'null', 'n/a']:
        return None

    for category, values in Gender_dict.items():
        if value in values:
            return category
    
    return None
def process_nationality(df):
    """Enhanced nationality processing with comprehensive error handling and .any() ambiguity resolution"""
    if df is None or df.empty:
        return df
    
    nationality_columns = [
        'NATIONALITY',
        'PRIMARYADDRESSCOUNTRY',
        'EMPLOYERCOUNTRY',
        'SECONDARYADDRESSCOUNTRY',
        'BUSINESSOFFICEADDRESSCOUNTRY',
        'REGISTEREDADDRESSCOUNTRY',
        'COUNTRYOFINCORPORATION',
        'CORPORATECOUNTRY',
        'PRINCIPALOFFICER1COUNTRY',
        'PRINCIPALOFFICER2COUNTRY',
        'GUARANTORSPRIMARYCOUNTRY',
        'GUARANTORSSECONDARYCOUNTRY'
    ]
    
    def clean_country_value(value):
        """Robust country value cleaning with detailed logging"""
        try:
            # Handle NaN or None values first
            if pd.isna(value) or value is None:
                return None        
            # Convert to string safely
            value = str(value).strip()          
            # Convert to lowercase and remove special characters
            value = value.lower()
            value = re.sub(r'[^a-zA-Z0-9\s]', '', value)           
            # Check for empty or invalid values
            if not value or value in ['none', 'nan', 'null', 'na']:
                return None          
            return value        
        except Exception as e:
            print(f"Error cleaning country value '{value}': {e}")
            return None
    def standardize_country(value):
        """Enhanced country standardization with detailed logging"""
        if value is None:
            return None       
        try:
            for standard_name, variations in Country_dict.items():
                if value in [v.lower() for v in variations]:
                    return standard_name           
            return None       
        except Exception as e:
            print(f"Error standardizing country '{value}': {e}")
            return None    
    # Find columns that exist in the DataFrame
    found_columns = [col for col in nationality_columns if col in df.columns]   
    for column in found_columns:        
        try:
            # Check if the column has any non-null values using .any()
            if df[column].notna().any():
                df[column] = df[column].apply(clean_country_value)
                df[column] = df[column].apply(standardize_country)              
            else:
                print(f"SKIP: No non-null values in column {column}")  
        except Exception as column_e:
            print(f"? FAILED to process column {column}: {column_e}")
            print(traceback.format_exc())
    return df


def remove_spaces(text):
    """Remove spaces from the input string."""
    if text is None:
        return ""
    return str(text).replace(" ", "")

    
def process_special_characters(df):
    """Remove special characters from all columns except specified ones, preserving '&' in address columns"""
    if df is None or df.empty:
        return df
    
    # List of columns to exclude from special character removal
    excluded_columns = [
        # Date columns
        'DATEOFBIRTH',
        'DATEOFINCORPORATION',
        'PRINCIPALOFFICER1DATEOFBIRTH',
        'PRINCIPALOFFICER2DATEOFBIRTH',
        'SPOUSEDATEOFBIRTH',
        'GUARANTORDATEOFBIRTHINCORPORATION',
        'LOANEFFECTIVEDATE',
        'MATURITYDATE',
        'LASTPAYMENTDATE',
        'DEFEREDPAYMENTDATE',
        'LITIGATIONDATE',
        'FACILITYTYPE',
        'BRANCHCODE',
        'BRANCH CODE',
        'CUSTOMERBRANCHUCODE',
        'CUSTOMERBRANCHCODE',
        'ACCOUNTNUMBER',
        'CUSTOMERSACCOUNTNUMBER',
        'EMAIL',
        'EMAILADDRESS',
        'PRINCIPALOFFICER1EMAILADDRESS',
        'PRINCIPALOFFICER2EMAILADDRESS',
        'GUARANTOREMAIL',
        'OUTSTANDINGBALANCE',
        'MONTHLYREPAYMENT',
        'TOTALREPAYMENT',
        'CREDITLIMIT',
        'AVAILEDLIMIT',
        'OUTSTANDINGBALANCE',
        'CURRENTBALANCEDEBT',
        'INSTALMENTAMOUNT',
        'OVERDUEAMOUNT',
        'LASTPAYMENTAMOUNT',
        'ACCOUNTSTATUSDATE',
    ]

    # List of columns that should preserve '&'
    address_columns = [
        'PRIMARYADDRESSLINE1',
        'PRIMARYADDRESSLINE2',
        'SECONDARYADDRESSLINE1',
        'SECONDARYADDRESSLINE2',
        'BUSINESSOFFICEADDRESSLINE1',
        'BUSINESSOFFICEADDRESSLINE2',
        'GUARANTORPRIMARYADDRESSLINE1',
        'GUARANTORPRIMARYADDRESSLINE2',
        'PRINCIPALOFFICER1PRIMARYADDRESSLINE1',
        'PRINCIPALOFFICER1PRIMARYADDRESSLINE2',
        'PRINCIPALOFFICER2PRIMARYADDRESSLINE1',
        'PRINCIPALOFFICER2PRIMARYADDRESSLINE2',
        'SECONDARYADDRESSCITYLGA',
        'BUSINESSOFFICEADDRESSCITYLGA',
        'GUARANTORPRIMARYADDRESSCITYLGA',
        'PRINCIPALOFFICER1CITY',
        'PRINCIPALOFFICER2CITY',
        'PRIMARYADDRESSCITY',
        'PRIMARYADDRESSSTATE',
        'SECONDARYADDRESSSTATE',
        'BUSINESSOFFICEADDRESSSTATE',
        'GUARANTORPRIMARYADDRESSSTATE',
        'PRINCIPALOFFICER1STATE',
        'PRINCIPALOFFICER2STATE',
        'PRIMARYADDRESSCOUNTRY',
        'SECONDARYADDRESSCOUNTRY',
        'BUSINESSOFFICEADDRESSCOUNTRY',
        'GUARANTORPRIMARYADDRESSCOUNTRY',
        'PRINCIPALOFFICER1COUNTRY',
        'PRINCIPALOFFICER2COUNTRY',
    ]

    # Find processable columns (those not in excluded list)
    processable_columns = [col for col in df.columns if col not in excluded_columns]
    
    for column in processable_columns:
        # Safely apply the transformation
        try:
            # Check if the column has any non-null values before processing
            if df[column].notna().any():
                if column in address_columns:
                    # Keep '&' in address columns
                    df[column] = df[column].apply(
                        lambda x: re.sub(r'[^a-zA-Z0-9&]', ' ', str(x)) if pd.notnull(x) else x
                    )
                elif column == 'COLLATERALDETAILS':
                    # Remove numeric characters from COLLATERAL DETAILS
                    df[column] = df[column].apply(
                        lambda x: re.sub(r'\d+', '', str(x)).strip() if pd.notnull(x) else x
                    )
                else:
                    # Remove special characters except '&' for other columns
                    df[column] = df[column].apply(
                        lambda x: re.sub(r'[^a-zA-Z0-9]', ' ', str(x)) if pd.notnull(x) else x
                    )
                
                # Remove double spaces
                df[column] = df[column].apply(lambda x: re.sub(r'\s+', ' ', x).strip() if isinstance(x, str) else x)
        except Exception as e:
            print(f"Error processing column {column}: {e}")

    # Now handle specific columns to remove spaces
    # ------------------------------------------------# take notr of this.-------------------------------------------------------
    for col in ['CUSTOMERID', 'TAXID', 'OTHERID','LEGALCHALLENGESTATUS','LOANSECURITYSTATUS']:
        if col in df.columns:
            df[col] = df[col].apply(remove_spaces)

    # Updated email processing logic
    email_columns = [
        'EMAILADDRESS', 
        'PRINCIPALOFFICER1EMAILADDRESS',
        'PRINCIPALOFFICER2EMAILADDRESS', 
        'GUARANTOREMAIL'
    ]
    
    for col in email_columns:
        if col in df.columns:
            try:
                # Convert to lowercase and filter valid emails
                df[col] = df[col].str.lower()
                # df[col] = df[col].apply(
                #     lambda x: x if pd.notnull(x) and 
                #     (x.endswith('@gmail.com') or x.endswith('@yahoo.com')) or x.endswith('.co.uk')) orx.endswith('.com')) 
                #     else ''
                # )
            except Exception as e:
                print(f"Error processing email column {col}: {e}")
    
    return df

def process_passport_number(df):
    """
    Cleans the Passport Number column based on specified criteria.
    
    Parameters:
    df (pd.DataFrame): The input DataFrame.
    
    Returns:
    pd.DataFrame: The updated DataFrame with valid Passport Numbers retained.
    """
    # List of Passport Number columns to process
    passport_columns = ['PASSPORTNUMBER']  # You can add more columns to this list if needed
    
    for column_name in passport_columns:
        if column_name in df.columns:
            # Function to clean Passport Number-
            def clean_passport(passport):
                # Convert to string
                passport_str = str(passport)
                passport_str = re.sub(r'[^a-zA-Z0-9]', '', passport_str)
                # Check if the value is numeric
                if passport_str.isdigit():
                    return ''  # Remove if purely numeric
                # Discard if the cleaned ID is not exactly 11 characters
                if len(passport_str) != 11:
                    return ''
                return passport_str  # Keep alphanumeric values

            # Apply the cleaning function to the PASSPORT_NUMBER column
            df[column_name] = df[column_name].apply(clean_passport)

    return df
def process_identity_numbers(df):
    """
    Cleans the National Identity Number columns based on specified criteria.
    
    Updated Criteria:
    - Each ID must be exactly 11 characters long. If the cleaned ID is not exactly 11 characters, it is discarded.
    - Each ID must start with two letters (case insensitive) immediately followed by a digit.
      If the starting pattern is not met, the ID is discarded.
    
    Parameters:
        df (pd.DataFrame): The input DataFrame.
    
    Returns:
        pd.DataFrame: The updated DataFrame with valid National Identity Numbers retained.
    """
    
    # List of National Identity Number columns to process
    identity_columns = [
        'NATIONALIDENTITYNUMBER',  
        'PRINCIPALOFFICER1NATIONALID',
        'PRINCIPALOFFICER2NATIONALID',
    ]
    
    for column_name in identity_columns:
        if column_name in df.columns:
            def clean_identity(identity):
                # Convert the value to a string
                identity_str = str(identity)
                # Remove all non-alphanumeric characters (i.e., spaces and special characters)
                identity_str = re.sub(r'[^a-zA-Z0-9]', '', identity_str)
                
                # Discard if the cleaned ID is not exactly 10 or 11 characters
                if len(identity_str) not in [10, 11]:
                    return ''
                
                # Check that the ID starts with two letters followed immediately by a digit.
                if not re.match(r'^[a-zA-Z]{2}\d', identity_str):
                    return ''
                
                return identity_str
            
            df[column_name] = df[column_name].apply(clean_identity)
    
    return df
def process_DriversLicense(df):
    """
    Cleans the Pendicomid columns based on specified criteria.
    
    Updated Criteria:
    - Each Pendicomid must be exactly 11 characters long. If the cleaned value is not exactly 11 characters, it is discarded.
    - Each Pendicomid must start with three letters (case insensitive) immediately followed by a digit.
      If the starting pattern is not met, the value is discarded.
    
    Parameters:
        df (pd.DataFrame): The input DataFrame.
    
    Returns:
        pd.DataFrame: The updated DataFrame with valid Pendicomid values retained.
    """
    
    # List of Pendicomid columns to process
    dLicense = [ 'DRIVERSLICENSENUMBER',
            'PRINCIPALOFFICER1DRIVERSLISCENCENUMBER',
            'PRINCIPALOFFICER2DRIVERSLISCENCENUMBER']  # You can add more columns to this list if needed
    
    for column_name in dLicense:
        if column_name in df.columns:
            def clean_driversLicense(value):
                # Convert the value to a string
                value_str = str(value)
                # Remove all non-alphanumeric characters (i.e., spaces and special characters)
                value_str = re.sub(r'[^a-zA-Z0-9]', '', value_str)
                
                # Discard if the cleaned value is not exactly 11 characters
                if len(value_str) != 11:
                    return ''
                
                # Check that the value starts with three letters (case insensitive) immediately followed by a digit.
                if not re.match(r'^[a-zA-Z]{3}\d', value_str):
                    return ''
                
                return value_str
            
            # Apply the cleaning function to the Pendicomid column
            df[column_name] = df[column_name].apply(clean_driversLicense)
    
    return df
def process_business_id(df):
    """
    Clears the values in the specified column where the values are not alphanumeric
    (containing both letters and numbers).
    
    Parameters:
    df (pd.DataFrame): The input DataFrame.
    column_name (str): The name of the column to process.
    
    Returns:
    pd.DataFrame: The updated DataFrame with non-alphanumeric values cleared in the specified column.
    """
    column_name = [
        'BUSINESSREGISTRATIONNUMBER',
        # Add any other relevant column names that may appear
    ]
    for col in column_name:
        if col in df.columns:
            # Convert to string and remove spaces and special characters
            df[col] = df[col].astype(str).apply(
                lambda x: ''.join(char for char in x if char.isalnum())
            )
            
            # Keep only values that contain both letters and numbers
            df[col] = df[col].where(
                df[col].str.contains(r'(?=.*[a-zA-Z])(?=.*\d)', regex=True), 
                ''
            )     
            # Replace 'nan' or 'None' with empty string
            df[col] = df[col].replace({'nan': '', 'None': ''})
    
    return df

def process_bvn_number(df):
    """
    Cleans the BVN number columns based on specified criteria.
    
    Parameters:
    df (pd.DataFrame): The input DataFrame.
    
    Returns:
    pd.DataFrame: The updated DataFrame with valid BVN values retained.
    """
    # List of BVN columns to process
    bvn_columns = ['BVNNUMBER',
                   'PRINCIPALOFFFICER1BVNNUMBER',
                   'PRINCIPALOFFICER2BVNNUMBER',
                   'GUARANTORBVN']  # You can add more columns to this list if needed
    
    for column_name in bvn_columns:
        if column_name in df.columns:
            # Function to clean BVN number
            def clean_bvn(bvn):
                # Convert to string
                bvn_str = str(bvn)
                # Check if the length is 11 and if it's numeric
                if len(bvn_str) == 11 and bvn_str.isdigit():
                    # Check if all characters are identical
                    if bvn_str == bvn_str[0] * 11:
                        return ''  # Remove if all characters are identical
                    return bvn_str  # Keep the valid BVN
                return ''  # Remove if not 11 digits or not numeric
            
            # Apply the cleaning function to the BVNNUMBER column
            df[column_name] = df[column_name].apply(clean_bvn)

    return df

# ---------------------------------------------------------------REMODIFY THIS---------------------------------------------------------------------
def process_otherid(df):
    """
    Cleans the National Identity Number columns based on specified criteria.
    
    Updated Criteria:
    - Each ID must be exactly 11 characters long. If the cleaned ID is not exactly 11 characters, it is discarded.
    - Each ID must start with two letters (case insensitive) immediately followed by a digit.
      If the starting pattern is not met, the ID is discarded.
    
    Parameters:
        df (pd.DataFrame): The input DataFrame.
    
    Returns:
        pd.DataFrame: The updated DataFrame with valid National Identity Numbers retained.
    """
    
    # List of Other Identity Number columns to process
    otherid_columns = [
       'OTHERID'
    ]
    
    for column_name in otherid_columns:
        if column_name in df.columns:
            def clean_otherid(other):
                # Convert the value to a string
                other_str = str(other)
                # Remove all non-alphanumeric characters (i.e., spaces and special characters)
                other_str = re.sub(r'[^a-zA-Z0-9]', '', other_str)
                
                # Discard if the cleaned ID is not exactly 10 or 11 characters
                if len(other_str) not in [10, 11]:
                    return ''
                
                # Check that the ID starts with one letters followed immediately by a digit.
                if not re.match(r'^[a-zA-Z]{1}\d', other_str):
                    return ''
                
                return other_str
            
            df[column_name] = df[column_name].apply(clean_otherid)
    
    return df



# Define the state columns
state_columns = [
    'STATE', 
    'PRIMARYADDRESSSTATE', 
    'SECONDARYADDRESSSTATE', 
    'EMPLOYERSTATE', 
    'BUSINESSOFFICEADDRESSSTATE', 
    'GUARANTORPRIMARYADDRESSSTATE', 
    'PRINCIPALOFFICER1STATE', 
    'PRINCIPALOFFICER2STATE'
]
# Define a function to perform fuzzy mapping
def fuzzy_map_state(state_name, state_dict):
    # Check if the state_name is empty or contains only whitespace
    if not state_name.strip():
        return None

    max_score = -1
    matched_state = None

    # Iterate through the state_dict and calculate fuzz ratio
    for state_code, names in state_dict.items():
        for name in names:
            score = fuzz.ratio(state_name.lower(), name.lower())
            if score > max_score:
                max_score = score
                matched_state = state_code

    # Define a threshold score (you can adjust this based on your requirements)
    threshold_score = 50

    # If the similarity score is above the threshold, return the corresponding state code
    if max_score >= threshold_score:
        return matched_state
    else:
        return None  # Return None if no good match is found

# Function to process state columns in the DataFrame
def process_states(consu):
    """Process state fields in the DataFrame"""
    for column in state_columns:
        if column in consu.columns and consu[column].apply(lambda x: not pd.isna(x) and str(x).strip() != '').any():
            # Clean and preprocess the column
            consu[column] = consu[column].apply(lambda x: str(x) if not pd.isna(x) else None)
            # Apply the fuzzy mapping function to non-empty values
            consu[column] = consu[column].apply(lambda x: fuzzy_map_state(x, state_dict) if not pd.isna(x) and str(x).strip() != '' else None)
        else:
            # No non-empty values found in the column, no action required
            pass
    return consu

def map_marital(value):
    if isinstance(value, str):
        for category, values in Marital_dict.items():
            if value in values:
                return category
    return None

def process_marital_status(df):
    """Process marital status fields in the DataFrame"""
    # Define the marital status columns to look for
    marital_columns = [
        'MARITALSTATUS',
        # Add any other relevant column names that may appear
    ]
    
    # Iterate through the list of potential marital status columns
    for col in marital_columns:
        if col in df.columns:
            # Clean the marital status values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(map_marital)
    
    return df

def map_borrowert(value):
    if isinstance(value, str):
        for category, values in Borrower_dict.items():
            if value in values:
                return category
    return None

def process_borrower_type(df):
    """Process borrower type fields in the DataFrame"""
    # Define the borrower type columns to look for
    borrower_columns = [
        'BORROWERTYPE'
        # Add any other relevant column names that may appear
    ]
    
    # Iterate through the list of potential borrower type columns
    for col in borrower_columns:
        if col in df.columns:
            # Clean the borrower type values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(map_borrowert)
    
    return df

def map_employers(value):
    if isinstance(value, str):
        for category, values in Employer_dict.items():
            if value in values:
                return category
    return None

def process_employment_status(df):
    """Process employment status fields in the DataFrame"""
    # Define the employment status columns to look for
    employment_columns = [
        'EMPLOYMENTSTATUS'
        # Add any other relevant column names that may appear
    ]
    
    # Iterate through the list of potential employment status columns
    for col in employment_columns:
        if col in df.columns:
            # Clean the employment status values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(map_employers)
    
    return df

def map_title(value):
    if isinstance(value, str):
        for category, values in Title_dict.items():
            if value in values:
                return category
    return None

def process_title(df):
    """Process title fields in the DataFrame"""
    # Define the title columns to look for
    title_columns = [
        'TITLE'
        # Add any other relevant column names that may appear
    ]
    
    # Iterate through the list of potential title columns
    for col in title_columns:
        if col in df.columns:
            # Clean the title values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(map_title)
    
    return df

def occu_title(value):
    if isinstance(value, str):
        for category, values in Occu_dict.items():
            if value in values:
                return category
        # If no match, check if the value is numeric
        if value.isdigit():
            return None  # Return None for numeric values
        # If the value is alphabetic, return it unchanged
        if value.isalpha():
            return value
    return None  # Return None for non-string types or unmatched cases

def process_occu(df):
    """Process title fields in the DataFrame"""
    # Define the title columns to look for
    occu_columns = [
        'OCCUPATION',
    ]
    
    # Iterate through the list of potential title columns
    for col in occu_columns:
        if col in df.columns:
            # Clean the title values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(occu_title)
    
    return df
#----------------------------------------------commented out business sector--------------------------------------------------
# def sec_title(value):
#     if isinstance(value, str):
#         # Check for matching values in the dictionary
#         for category, values in sec_dict.items():
#             if value in values:
#                 return category
#         # If no match, check if the value is numeric
#         if value.isdigit():
#             return None  # Return None for numeric values
#         # If the value is alphabetic, return it unchanged
#         if value.isalpha():
#             return value
#     return None  # Return None for non-string types or unmatched cases

# def process_business_sector(df):
#     """Process business sector fields in the DataFrame"""
#     # Define the business sector columns to look for
#     sector_columns = [
#         'BUSINESSSECTOR',
#         # Add any other relevant column names that may appear
#     ]
    
#     # Iterate through the list of potential business sector columns
#     for col in sector_columns:
#         if col in df.columns:
#             # Clean the business sector values
#             df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
#             df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
#             df[col] = df[col].apply(sec_title)
    
#     return df


def map_accountStatus(value):
    """Maps account status values to standardized format."""
    if pd.isna(value) or value is None:
        return None
    
    # Convert to string and clean
    value = str(value).lower()
    value = re.sub(r'[^a-zA-Z0-9]', '', value)
    
    for category, values in AccountStatus_dict.items():
        # Convert dictionary values to lowercase and remove special characters for comparison
        dict_values = [str(v).lower().replace(r'[^a-zA-Z0-9]', '') for v in values]
        if value in dict_values:
            return category
    return None  # Return None if no match is found

def clear_previous_info_columns(df):
    """
    Clear the contents of previous information columns while keeping headers
    """
    columns_to_clear = [
        'PREVIOUSACCOUNTNUMBER',
        'PREVIOUSNAME',
        'PREVIOUSCUSTOMERID',
        'PREVIOUSBRANCHCODE',
        'BUSINESSSECTOR',
        'PICTUREFILEPATH'
    ]
    
    print("\n=== CLEARING PREVIOUS INFO COLUMNS ===")
    for col in columns_to_clear:
        if col in df.columns:
            df[col] = ''
    print("Previous info columns cleared")  
    return df

def process_account_status(df):
    """Process account status fields in the DataFrame."""
    # Define the account status columns to look for
    status_columns = [
        'ACCOUNTSTATUS',
        'STATUS', 

    ]

    # Iterate through the list of potential account status columns
    for col in status_columns:
        if col in df.columns:
            print(f"Processing account status column: {col}")
            
            # Clean the account status values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(map_accountStatus)
            
            # Print unique values after processing
            print(f"Unique values in {col} after processing:", df[col].unique())
    
    return df
def exact_map_loan(loan_name):
    loan_name_lower = loan_name.lower()

    # Iterate through the Loan_dict and look for an exact match
    for loan_code, names in Loan_dict.items():
        if loan_name_lower in [name.lower() for name in names]:
            return loan_code

    # Return None if no exact match is found
    return None

def process_loan_type(df):
    """Process business sector fields in the DataFrame"""
    # Define the business sector columns to look for
    loan_columns = [
        'FACILITYTYPE',
        # Add any other relevant column names that may appear
    ]
    
    # Iterate through the list of potential business sector columns
    for col in loan_columns:
        if col in df.columns:
            # Clean the business sector values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(exact_map_loan)
    
    return df
def map_currency(value):
    """Maps currency values to standardized format."""
    if pd.isna(value) or value is None:
        return None
    
    # Convert to string and clean
    value = str(value).lower()
    value = re.sub(r'[^a-zA-Z0-9]', '', value)
    
    for category, values in Currency_dict.items():
        # Convert dictionary values to lowercase and remove special characters for comparison
        dict_values = [str(v).lower().replace(r'[^a-zA-Z0-9]', '') for v in values]
        if value in dict_values:
            return category
    return None   # Return None if no match is found

def process_currency(df):
    """Process currency fields in the DataFrame."""
    currency_columns = [
        'CURRENCY'
    ]
    
    for col in currency_columns:
        if col in df.columns:
            print(f"Processing currency column: {col}")
            
            # Clean the currency values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9\s]', '', x) if isinstance(x, str) else x)  # Allow spaces
            df[col] = df[col].apply(map_currency)
            
            # Print unique values after processing
            print(f"Unique values in {col} after processing:", df[col].unique())
    
    return df

def map_repayment(value):
    """Maps repayment values to standardized format."""
    for category, values in Repayment_dict.items():
        if value in values:
            return category
    return None  # Return None if no match is found

def process_repayment(df):
    """Process repayment fields in the DataFrame."""
    repayment_columns = ['REPAYMENTFREQUENCY']  # Define the repayment columns to look for
    
    for col in repayment_columns:
        if col in df.columns:
            # Clean the repayment values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9\s]', '', x) if isinstance(x, str) else x)  # Allow spaces
            df[col] = df[col].apply(map_repayment)
    
    return df
def map_collateraltype(value):
    for category, values in Collateraltype_dict.items():
        if value in values:
            return category
    return None

def process_collateral_type(df):
    """Process collateral type fields in the DataFrame."""
    collateral_columns = ['COLLATERALTYPE']  # Define the collateral type columns to look for
    
    for col in collateral_columns:
        if col in df.columns:
            # Clean the collateral type values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)  # Allow spaces
            df[col] = df[col].apply(map_collateraltype)
    
    return df
def map_classification(value):
    """Maps classification values to standardized format."""
    if pd.isna(value) or value is None:
        return None  # Return None for NaN or None values

    if not isinstance(value, str):
        value = str(value)  # Convert to string if not already

    # Check against the Classification_dict
    for category, values in Classification_dict.items():
        if value in values:
            return category  # Return the matched category

    return None 
def process_classification(df):
    """Process classification fields in the DataFrame."""
    classification_columns = ['LOANCLASSIFICATION']  # Define the classification columns to look for
    
    for col in classification_columns:
        if col in df.columns:
            # Clean the classification values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9\s]', '', x) if isinstance(x, str) else x)  # Allow spaces
            df[col] = df[col].apply(map_classification)  # Apply the mapping function
    
    return df

def process_phone_columns(df):
    """
    Process numeric columns including telephone numbers
    """
    # Define columns that need numeric processing
    phone_columns = [
        'MOBILENUMBER', 'WORKTELEPHONE', 'HOMETELEPHONE', 
        'PRIMARYPHONENUMBER', 'SECONDARYPHONENUMBER',
        'PRINCIPALOFFICER1PHONENUMBER', 'PRINCIPALOFFICER2PHONENUMBER',
        'GUARANTORPRIMARYPHONENUMBER'
    ]
    
    try:
        if df is not None and not df.empty:
            # Process phone number columns
            for col in phone_columns:
                if col in df.columns:
                    print(f"Processing phone number column: {col}")
                    df[col] = df[col].astype(str)
                    # Keep only the first number before any comma
                    df[col] = df[col].apply(lambda x: x.split(',')[0] if ',' in x else x)
                    # Remove any non-numeric characters
                    df[col] = df[col].apply(lambda x: ''.join(filter(str.isdigit, str(x))) if pd.notna(x) else '')
                    # Pad with zeros if less than 11 digits
                    df[col] = df[col].apply(lambda x: x.zfill(11) if x and len(x) < 11 else x)
                     # New validation: Check if number > 11 digits and doesn't start with 234
                    df[col] = df[col].apply(lambda x: '' if len(x) > 11 and not x.startswith('234') else x)

                    # New validation: Remove numbers not starting with 07, 08, or 09
                    # df[col] = df[col].apply(lambda x: x if (x.startswith(('07', '08', '09')) or (x.startswith('234') and len(x) == 13)) else '')
                    # New validation: Check for first two digits being the same
                    # df[col] = df[col].apply(lambda x: '' if x and len(x) >= 2 and x[0] == x[1] else x)

                    # Remove numbers that are more than 14 characters
                    df[col] = df[col].apply(lambda x: x if len(x) <= 13 else '')

                    # New validation: Check for more than 5 consecutive same digits
                    def has_repeating_sequence(number):
                        if not number:
                            return False
                        count = 1
                        prev_digit = number[0]
                        for digit in number[1:]:
                            if digit == prev_digit:
                                count += 1
                                if count > 5:
                                    return True
                            else:
                                count = 1
                                prev_digit = digit
                        return False
                    
                    df[col] = df[col].apply(lambda x: '' if has_repeating_sequence(x) else x)
                    
                    # Remove repetitive numbers (e.g., 00000000000, 11111111111)
                    df[col] = df[col].apply(lambda x: '' if x and len(set(x)) == 1 else x)
                    # Replace 'nan' with empty string
                    df[col] = df[col].replace({'nan': ''})
    
    except Exception as e:
        print(f"Error in process_phone_columns: {e}")
        traceback.print_exc()
    
    return df

def convert_tenor_to_days(tenor: Union[str, int, float]) -> Optional[int]:
    """Converts a composite tenor string (e.g., '2 month 3 weeks') to a total number of days.

    If the input is a number (without unit), it returns that number as an integer.
    It handles multiple number-unit pairs by summing their respective day conversions.
    
    Supported units (case-insensitive):
        - days/d or day
        - weeks/w or week
        - months/m or month
        - years/y or year
    """
    if tenor is None or tenor == '':
        return None

    # If the input is already numeric, return it as integer
    if isinstance(tenor, (int, float)):
        return int(tenor)

    # Convert to string and normalize to lower-case
    tenor_str = str(tenor).strip().lower()

    # Optional: Convert written-out numbers (like "two", "three") to digits using w2n.
    try:
        tenor_str = re.sub(
            r'\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b',
            lambda m: str(w2n.word_to_num(m.group())), tenor_str)
    except Exception as ex:
        # If conversion fails, just proceed with the original string.
        pass

    # Define a regex pattern that finds multiple number-unit pairs
    pattern = r'(\d+(?:\.\d+)?)\s*(days?|weeks?|months?|years?|d|w|m|y)'
    matches = re.findall(pattern, tenor_str)

    total_days = 0
    if matches:
        # Define mapping between recognized units and their day multipliers
        unit_mapping = {
            'day': 1,
            'days': 1,
            'd': 1,
            'week': 7,
            'weeks': 7,
            'w': 7,
            'month': 30,
            'months': 30,
            'm': 30,
            'year': 365,
            'years': 365,
            'y': 365,
        }
        for num_str, unit in matches:
            try:
                number = float(num_str)
            except ValueError:
                continue  # Skip if conversion fails
            multiplier = unit_mapping.get(unit, None)
            if multiplier is not None:
                total_days += number * multiplier
        # Return total days as an integer
        return int(total_days)
    else:
        # Fallback: If no unit-pattern was found, try converting the whole string to a number
        try:
            return int(float(tenor_str))
        except ValueError:
            return None
def process_loan_tenor(df):
    """
    Process loan tenor column in the DataFrame.
    Args:
        df: Input DataFrame
    Returns:
        DataFrame with processed loan tenor
    """
    if df is None:
        print("Input DataFrame is None.")
        return None

    if not isinstance(df, pd.DataFrame):
        print("Input is not a valid DataFrame.")
        return None

    # Columns to process for loan tenor
    tenor_columns = [ 'FACILITYTENOR',
                     'DAYSINARREARS']

    # Process each potential tenor column
    for col in tenor_columns:
        if col in df.columns:
            print(f"Processing column: {col}")

            # Apply conversion

            df[col] = df[col].apply(convert_tenor_to_days)
            # Convert to numeric, handling any conversion errors
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            df[col] = df[col].astype(str)
        else:
            print(f"Column {col} not found in DataFrame.")

    return df

def try_convert_to_float(x):
    """
    Enhanced numeric conversion function to handle mixed alphanumeric values
    
    Args:
        x: Input value to convert
    
    Returns:
        Converted float as string if successful, otherwise returns cleaned value with commas removed
    """
    # If input is None or empty, return empty string
    if pd.isna(x) or x == '':
        return ''
    
    # Convert to string if not already and strip leading/trailing spaces
    x = str(x).strip()
    
    # Remove specific special characters and leading/extra spaces
    x = re.sub(r'[-₦]', '', x)  # Remove specific special characters
    x = re.sub(r'\s+', ' ', x)  # Replace multiple spaces with a single space

    # First, check if the string is fully numeric (with a single decimal point)
    if re.match(r'^[0-9]+(\.[0-9]+)?$', x):
        try:
            float_value = float(x)
            return '{:.2f}'.format(float_value)
        except:
            return x
    
    try:
        # Remove any non-numeric characters except decimal point
        cleaned_value = re.sub(r'[^0-9.]', '', x)
        
        # If nothing remains after cleaning, return original value
        if not cleaned_value:
            return x
        
        # Count decimal points
        if cleaned_value.count('.') > 1:
            # If multiple decimal points, it's likely a formatting issue
            # Return the cleaned value (with commas removed) but don't try to convert
            return cleaned_value
        
        # Convert to float and format to 2 decimal places
        float_value = float(cleaned_value)
        return '{:.2f}'.format(float_value)
    
    except (ValueError, TypeError) as e:
        # If conversion fails, return the cleaned value with commas removed
        return cleaned_value if 'cleaned_value' in locals() else x

def process_numeric_columns(df):
    """Process numeric columns to standardize their format"""
    numeric_columns = [
        'AVAILEDLIMIT', 
        'CREDITLIMIT',
        'OVERDUEAMOUNT',
        'LASTPAYMENTAMOUNT',
        'INSTALMENTAMOUNT',
        'INCOME',
        'OUTSTANDINGBALANCE'
    ]
    
    for col in numeric_columns:
        if col in df.columns:
            print(f"Processing numeric column: {col}")
            
            # Apply the enhanced conversion function - this will retain original values that can't be converted
            df[col] = df[col].apply(try_convert_to_float)
            
            # Print sample values after processing for verification
            print(f"Sample values in {col} after processing:")
            print(df[col].head())
    
    return df

def trim_strings_to_59(df):
    """
    Trim all string values in the DataFrame to 59 characters maximum
    
    Args:
        df (pd.DataFrame): Input DataFrame
        
    Returns:
        pd.DataFrame: DataFrame with all string values trimmed to 59 characters
    """
    # Define the trimming function
    def trim_string(s):
        if isinstance(s, str) and len(s) > 59:
            return s[:58]  # Trim to 58 characters as requested
        return s
    
    # Apply the function to all elements in the DataFrame
    print("\n=== TRIMMING STRING VALUES TO 59 CHARACTERS ===")
    df = df.applymap(trim_string)
    print("String trimming completed")
    
    return df

def merge_individual_borrowers(consu, credit, guar):
    """Merge individual borrower DataFrames"""
    # Validate DataFrames
    if consu.empty or credit.empty:
        print("Warning: Individual borrower or credit information DataFrame is empty")
        return pd.DataFrame()
    
    # Filter out rows with empty or blank 'CUSTOMERID'
    consu_cleaned = consu[
        consu['CUSTOMERID'].notna() & 
        (consu['CUSTOMERID'].str.strip() != '')
    ]
    
    # Merge attempts for individual borrowers
    merge_attempted = False
    indi = pd.DataFrame()  # Initialize indi DataFrame
    
    try:
        # First attempt: Merge on CUSTOMERID
        if 'CUSTOMERID' in credit.columns:
            print("Attempting primary merge on CUSTOMERID")
            indi = pd.merge(
                consu_cleaned, 
                credit, 
                on='CUSTOMERID', 
                how='inner',
                indicator=True  # Add merge indicator
            )
            print(f"Primary merge matches: {indi.shape[0]} rows")
            print("Merge indicator counts:")
            print(indi['_merge'].value_counts())
            indi = indi.drop(columns=['_merge'])
            merge_attempted = True
    except Exception as e:
        print(f"Primary merge failed: {str(e)}")

    # Fallback if primary merge failed or resulted in empty DataFrame
    if not merge_attempted or indi.empty:
        print("Attempting fallback merge with ACCOUNTNUMBER")
        try:
            if 'ACCOUNTNUMBER' in credit.columns:
                # Use outer join temporarily to analyze matches
                temp_merge = pd.merge(
                    consu_cleaned,
                    credit,
                    left_on='CUSTOMERID',
                    right_on='ACCOUNTNUMBER',
                    how='outer',
                    indicator=True
                )
                print("Fallback merge analysis:")
                print(temp_merge['_merge'].value_counts())
                
                # Perform actual inner join
                indi = temp_merge[temp_merge['_merge'] == 'both'].copy()
                if not indi.empty:
                    indi = indi.drop(columns=['_merge'])
                    
                    # Drop CUSTOMERID from credit if it exists
                    if 'CUSTOMERID_y' in indi.columns:
                        indi = indi.drop(columns=['CUSTOMERID_y'], errors='ignore')  # Drop the credit CUSTOMERID if it exists
                        
                    # Rename CUSTOMERID_x to CUSTOMERID
                    if 'CUSTOMERID_x' in indi.columns:
                        indi = indi.rename(columns={'CUSTOMERID_x': 'CUSTOMERID'})
                    
                    print(f"Fallback merge successful: {indi.shape[0]} rows")
                else:
                    print("Warning: Fallback merge resulted in empty DataFrame")
        except Exception as e:
            print(f"Fallback merge failed: {str(e)}")
            return pd.DataFrame()

    if indi.empty:
        print("Error: All merge attempts failed to produce results")
        print("Consu shape:", consu_cleaned.shape)
        print("Credit shape:", credit.shape)
        return pd.DataFrame()

    # Merge with guarantor information
    try:
        indi = pd.merge(
            indi,
            guar,
            left_on='ACCOUNTNUMBER',
            right_on='CUSTOMERSACCOUNTNUMBER',
            how='left'
        )
        print(f"Guarantor merge successful. Final shape: {indi.shape}")
    except Exception as e:
        print(f"Guarantor merge failed: {str(e)}")
    # else:
    #     print("No guarantor information available")
    return indi

def merge_corporate_borrowers(comm, credit, prin):
    """Merge corporate borrower DataFrames"""
    # Validate DataFrames
    if comm.empty or credit.empty:
        print("Warning: Corporate borrower or credit information DataFrame is empty")
        return pd.DataFrame()
    
    # Filter out rows with empty or blank 'CUSTOMERID'
    comm_cleaned = comm[
        comm['CUSTOMERID'].notna() & 
        (comm['CUSTOMERID'].str.strip() != '')
    ]
    
    # Merge attempts for corporate borrowers
    merge_attempted = False
    corpo = pd.DataFrame()  # Initialize corpo DataFrame
    
    try:
         # First attempt: Merge on CUSTOMERID
        if 'CUSTOMERID' in credit.columns:
            print("Attempting primary merge on CUSTOMERID")
            corpo = pd.merge(
                comm_cleaned, 
                credit,
                on='CUSTOMERID', 
                how='inner',
                indicator=True
            )
            print(f"Primary merge matches: {corpo.shape[0]} rows")
            print("Merge indicator counts:")
            print(corpo['_merge'].value_counts())
            corpo = corpo.drop(columns=['_merge'])
            merge_attempted = True
    except Exception as e:
        print(f"Primary merge failed: {str(e)}")
# Fallback if primary merge failed or resulted in empty DataFrame
    if not merge_attempted or corpo.empty:
        print("Attempting fallback merge with ACCOUNTNUMBER")
        try:
           if 'ACCOUNTNUMBER' in credit.columns:
                # Use outer join temporarily to analyze matches
                temp_merge = pd.merge(
                    comm_cleaned,
                    credit,
                    left_on='CUSTOMERID',
                    right_on='ACCOUNTNUMBER',
                    how='outer',
                    indicator=True
                )
                print("Fallback merge analysis:")
                print(temp_merge['_merge'].value_counts())
 # Perform actual inner join
                corpo = temp_merge[temp_merge['_merge'] == 'both'].copy()
                if not corpo.empty:
                    corpo = corpo.drop(columns=['_merge'])
                    
                    # Drop CUSTOMERID from credit if it exists
                    if 'CUSTOMERID_y' in corpo.columns:
                        corpo = corpo.drop(columns=['CUSTOMERID_y'], errors='ignore')  # Drop the credit CUSTOMERID if it exists
                        
                    # Rename CUSTOMERID_x to CUSTOMERID
                    if 'CUSTOMERID_x' in corpo.columns:
                        corpo = corpo.rename(columns={'CUSTOMERID_x': 'CUSTOMERID'})
                    
                    print(f"Fallback merge successful: {corpo.shape[0]} rows")
                else:
                    print("Warning: Fallback merge resulted in empty DataFrame")
        except Exception as e:
            print(f"Fallback merge failed: {str(e)}")
            return pd.DataFrame()

    if corpo.empty:
        print("Error: All merge attempts failed to produce results")
        print("Consu shape:", comm_cleaned.shape)
        print("Credit shape:", credit.shape)
        return pd.DataFrame()
    print("After merging with credit (inner join):")
    print("corpo shape:", corpo.shape)


    # Merge with principal officers information
    try:
        corpo = pd.merge(
            corpo,
            prin,
            left_on='CUSTOMERID',
            right_on='CUSTOMERID',
            how='left'
        )
        print(f"principal merge successful. Final shape: {corpo.shape}")
    except Exception as e:
        print(f"Principal merge failed: {str(e)}")
    # else:
    #     print("No principal information available")
    corpo.drop(columns=['FACILITYOWNERSHIPTYPE', 'INCOME', 'INCOMEFREQUENCY', 'OWNERTENANT', 'NUMBEROFPARTICIPANTSINJOINTLOAN', 'DEPENDANTS'], inplace=True)
    return corpo

def remove_duplicates(df, columns_to_check=None):
    """
    Remove duplicates from DataFrame to mimic Excel's Remove Duplicates feature
    
    Args:
        df (pd.DataFrame): Input DataFrame
        columns_to_check (list, optional): Columns to check for duplicates (like Excel's column selection)
                                          If None, all columns are used
    
    Returns:
        pd.DataFrame: Cleaned DataFrame with duplicates removed
    """
    if df is None or df.empty:
        return df
    
    # If no columns specified, use all columns (like Excel default)
    if columns_to_check is None or len(columns_to_check) == 0:
        columns_to_check = df.columns.tolist()
    else:
        # Only use columns that actually exist in the dataframe
        columns_to_check = [col for col in columns_to_check if col in df.columns]
        
        if not columns_to_check:
            print("None of the specified columns found in DataFrame. Using all columns.")
            columns_to_check = df.columns.tolist()
    
    # Create a copy for case-insensitive comparison
    df_clean = df.copy()
    
    # Make string comparisons case-insensitive like Excel
    for col in columns_to_check:
        if df_clean[col].dtype == 'object':  # Only process string columns
            # Convert to lowercase for case-insensitive comparison (like Excel)
            df_clean[col] = df_clean[col].astype(str).str.lower()
            
            # Excel ignores leading/trailing spaces in comparisons
            df_clean[col] = df_clean[col].str.strip()
    
    # Perform duplicate removal (keeping first occurrence like Excel)
    # Get indices of rows to keep
    indices_to_keep = df_clean.drop_duplicates(
        subset=columns_to_check,
        keep='first'
    ).index
    
    # Use original dataframe with these indices to preserve original data
    df_cleaned = df.loc[indices_to_keep].reset_index(drop=True)
    
    # Log removed rows
    rows_removed = len(df) - len(df_cleaned)
    if rows_removed > 0:
        print(f"Removed {rows_removed} duplicate rows")
    
    return df_cleaned

def is_commercial_entity(name, commercial_keywords):
    """
    Check for commercial entities by looking at standalone words
    
    Args:
        name (str): Full name to check
        commercial_keywords (list): List of commercial keywords
    
    Returns:
        bool: True if likely a commercial entity, False otherwise
    """
    if not isinstance(name, str):
        return False
    
    # Convert to lowercase and split into words
    name_words = set(name.lower().split())
    
     # Convert keywords to lowercase for case-insensitive comparison
    commercial_keywords_lower = [keyword.lower() for keyword in commercial_keywords]
    # Check for standalone commercial keywords
    commercial_matches = [
        keyword for keyword in commercial_keywords_lower
        if keyword in name_words
    ]
    
    # Debug print for analysis
    if commercial_matches:
        print(f"Potential commercial entity detected: {name}")
        print(f"Matched standalone keywords: {commercial_matches}")
    
    return len(commercial_matches) > 0

def split_commercial_entities(indi):
    """Split commercial entities from individual borrowers
    
    Args:
        indi (pd.DataFrame): Individual borrowers DataFrame
    
    Returns:
        tuple: (Individual borrowers DataFrame, Commercial entities DataFrame)
    """
    # More comprehensive commercial keywords
    commercial_keywords = [
    "CREDIT", "GVL", "LOA", "POL", "SON", "NIG", "LTD", "AAWUNPCU",'Trader', 'farmer', 'life stock','livestock','chowdeck',
    "ASUU", "AAWUN", "ACADEMI", "ACADEMY", "ACCT", "ADCOMTECH", "ADVISER", "ADVOCATE", "ADVOCATES",'blooms',
    "AFFAIRS", "AGENCIES", "AGENCY", "AGENDA", "AGRIC", "AGRICULTURAL", "AGRICULTURE", "ALLIED", "ALLOCATION", "ALUMINIUM",
    "ANGLICAN", "ANNOINTED",  "ASSEMBLIES", "ASSEMBLY", "ASSETS", "ASSICIATES", "ASSOCIATE", "ASSOCIATES", "ASSOCIATION",
    "ASSOCIATIONS", "ASSOUTION", "AUTO",  "BATHROOM", "BIOMEDICAL", "BOARD", "BOARDS", "BRANCH", "BREAK",
    "BROKERS", "BROTHERS", "BUREAU", "BUSINESS", "BUTCHERS", "CAFETERIA", "CAMP", "CAPITAL", "CARPET",
    "CARPETS", "CARS", "CATERING", "CCTU", "CELLULAR", "CEMENT", "CENTER", "CENTRE", "CHALLENGE", "CHAMBERS",
    "CHANGE", "CHAPTER", "CHARISMATIC", "CHEMICAL", "CHEMICALS", "CHEMISTS", "CHICKEN", "CHURCH", "CITIZEN", "CITIZENS",
    "CLAY", "CLINIC", "CLOSET", "CLUB", "COOPERATIVE", "COEASU", "COHEADS", "COLLECTION", "COLLECTIONS", "COLLEGE",
    "COLOUR",  "COMMERCIAL", "COMMUNICA", "COMMUNICATION", "COMMUNICATIONS", "COMP", "COMPANY", "COMPRHENSIVE", "COMPUTER",
    "COMPUTERS", "CONCEPT", "CONCEPTS", "CONFERENCE", "CONFRENCE", "CONNECT", "CONSORTIUM", "CONST", "CONSTR", "CONSUING",
    "CONSUINGD", "CONSULT", "CONSULTA", "CONSULTANCY", "CONSULTANTS", "CONSULTING", "CONSUMERS", "CONTACT", "CONTRACTOR", "CONTRACTORS",
    "CONTROL", "COOP", "CORP", "CORPORATES", "CORPORATION", "COUNCIL", "COY", "CRADLES", "CREATIONS", "CTV",
    "CURRENT", "DEPARTMENT", "DEPOT", "DEPT", "DESIGN", "DESIGNS", "DEV", "DEVELOPME", "DEVELOPMENT", "DIGITAL",
    "DIOCESE", "DIRECTORATE", "DISABLE", "DISPENSARY", "DIST", "DISTRICT", "DIVERSIFIED", "DIVISION", "DOCKYARD", "DORMANT",
    "DRILL", "DRINK", "DRINKS", "DRIVERS", "EAST", "ECOBANK", "EDUCATION", "ELECRO", "ELECT", "ELECTRICAL",
    "ELECTRICITY", "ELECTRO", "ELECTROMART", "ELECTRONIC", "ELECTRONICS", "EMAGITIONS", "EMBASSY", "EMPLOYEE", "EMPORIUM", "ENERGY",
    "ENGINEERING", "ENGINEERS", "ENT", "ENTERPRIS", "ENTERPRISE", "ENVIROMENT", "EQUIPMENT", "ESTATE", "ESTATES", "EXECUTIVE",
    "EXERCISE", "EXPENDITURE", "EXPORT", "EXPORTS", "FABRIC", "FAMILY", "FARM", "FARMER", "FARMERS", "FARMS",
    "FEDERAL", "FINANCE", "FITNESS", "FOOD", "FOODS", "FORMATIONS", "FORUM", "FOUNDATION", "FOURSQUARE", "FRIENDSHIP",
    "FROZEN", "FURNISHING", "FURNITURE", "FURNITURES", "FUTURE", "GADGET", "GALLERIA", "GARDENS", "GARMENTS", "GENERAL",
    "GEOINFORMATIC", "GEOPLANNERS", "GIFTS", "GLOBA", "GLOBAL", "GLOBE", "GOV", "GOVERNMENT", "GOVT", "GRASSROOTS",
    "GREENSPRINGS", "GROUP", "GROWERS", "GRP", "GYARTAGERE", "HEALTH", "HELP", "HIGH COURT", "HOLDINGS", "HOMES",
    "HOSPITA", "HOSPITAL", "HOSPITALITY", "HOTEL", "HOUSE", "HOUSES", "IMPEX", "IMPORT", "IMPORTS", "IMPRESSION",
    "IND", "INDUSTR", "INDUSTRIE", "INDUSTRIES", "INDUSTRY", "INFINITY", "INFRASTRUCTURE", "INSPECTORATE", "INSPIRATIONAL", "INST",
    "INSTANTE", "INSTITUTE", "INSTITUTUE", "INSURANCE", "INTEGRA", "INTEGRAL", "INTERCONTINENTAL", "INTERNAL", "INTERNATIONA", "INTERNATIONAL",
    "INTL", "INV", "INVESMENT", "INVESMENTS", "INVESTMEN", "INVESTMENT", "INVESTMENTS", "INVESTMESTS", "JOINT", "KAD",
    "KONSULT", "L E A", "LEA", "LGE A", "LAB", "LABORATORIES", "LABORATORY", "LAPTOP", "LEASING", "LEGACY",
    "LEGAL", "LEISURE", "LGA", "LGEA", "LIBRARY",  "LIMI", "LIMIT", "LIMITE", "LIMITED",
    "LIMTED", "LIVING", "LOANS", "LOCAL", "LOGISTICS", "LOKOJA", "MACRO", "MAGER", "MANAGEMENT", "MANAGERS",
    "MANUFACT", "MANUFACTURE", "MANUFACTURERS", "MANUFACTURING", "MARBLE", "MARKET", "MARKETING", "MASHIDIMAMI", "MATHNIC", "MEDIA",
    "MEDICAL", "MERCHANDISE", "MGMT", "MICRO", "MICROFINANCE", "MILLENNIUM", "MINERAL", "MINERALS", "MINING", "MINISTRIES",
    "MINISTRY", "MINTING", "MISSION", "MOBILE", "MODERN", "MOSQUE", "MOTORS", "MPCS", "MULTI", "MULTIPURPOSE",
    "MULTITECH", "MUSICIANS", "Markert", "Marketers", "N U T",  "NATIONAL", "NETWORK", "NIGERIA", "NOODLES",
    "NORTH", "NURSERY", "NUT", "OCEAN", "OFFICE", "OFFSHORE", "OFPHYSICAL", "OGSG", "OPINION", "ORG",'cup',
    "ORGANISATION", "ORGANIZATION", "ORIENTAL", "OUTLOOK", "OVERHEAD", "PAINT", "PARTNER", "PARTS", "PAVILION", "PENSION",
     "PERFORMANCE", "PERFORMING", "PETROCHEMICALS", "PETROLEUM", "PETROLSEAL", "PETROSERVE", "PFA", "PHARMA", "PHARMACEUTICAL",
    "PHYSIOTHERAPY", "PILLAR", "PLACE", "PLASTIC", "PLAZA", "PLC", "POINT", "POLITICAL", "POLYMALT", "POLYMER",
    "POLYTECHNIC", "POULTRY", "POVERTY", "PRECID", "PRIMARY", "PRINT", "PRINTING", "PRINTS", "PRIVATE", "PROD",
    "PRODUCT", "PRODUCTIONS", "PRODUCTS", "PROFILE", "PROJECT", "PROJECTS", "PROPERTIES", "PROPERTY", "PROVINCE", "PRY",
    "PUBLIC", "PUBLICATION",  "PYRAMID", "QUANTITEQUE", "RCCG", "RATTAWU", "REALITIES", "REALTOR", "REALTORS",
    "RECIPE", "REDUCTION", "REFUGE", "REGISTRAR", "REHOBOTH", "REMITTANCE", "REMMT", "RENTAL", "RESEARCH", "RESORT",
    "RESORTS", "RESOURCE", "RESOURCES", "RESOURSES", "RESTAURANT", "RESTURANT", "REVENUE", "ROCKS", "ROOFING", "RURAL",
    "Relations", "Resources", "Restructure", "SADP", "SEPA", "SGARI", "SAFETY", "SALES", "SALON",
    "SANCTUARY", "SAVINGS", "SAVIOURS", "SCH", "SCHEME", "SCHEMES", "SCHOOL", "SCHOOLS", "SCIENTIFIC", "SECODARY",
    "SECONDARY", "SECRETARIAT", "SECURITIES", "SECURITY", "SEEDS", "SELLER", "SELLERS", "SERV", "SERVANT", "SERVANTS",
    "SERVI", "SERVICES", "SHARES", "SHIPPING", "SOCEITY", "SOCIETY", "SOLICITOR", "SOLICITORS",
    "SOLID", "SOLUTION", "SOLUTIONS", "SONS", "SOTER", "SOUND", "SOUTH", "SPARE", "SPECIAL", "SPIRITUAL",
    "SPORT", "SPORTS", "SPRAYING", "SSANIP", "STANDARD", "STATE", "STATION", "STEEL", "STOC", "STOCK",
    "STORE", "STORES", "STRATEGIC", "STRUCTURAL", "STUDENTS", "SUBSCRIPTION", "SUBSTANCE", "SUITES", "SUPER", "SUPPLY",
    "SUPPY", "SURPRISES", "SURVEILLANCE", "SURVEY", "SYSTEM", "SYSTEMS", "TABERNACLE", "TABLE", "TAX", "TEC",
    "TECHNICAL", "TECHNO", "TECHNOLOGIE", "TECHNOLOGIES", "TELECOMS", "TELEVISION", "TEXTILES", "THEME", "THINKING", "TIMELESS",
    "TODDLERS", "TOTAL", "TOURIST", "TRADE", "TRADER", "TRADERS", "TRADING", "TRAINING", "TRANS", "TRAVEL",
    "TRAVELS", "TRUCK", "TRUCKS", "Traditional",  "UNIMAID", "UNION", "UNIONS", "UNIV", "UNIVERSITY",
    "USERS", "VALLEY", "VENT", "VENTURE", "VENTURES", "VESSEL", "VESSELS",  "WA", "WMPCS","sociaty","co operative",
    "WARD",  "WIRELESS", "WOMEN", "WOMEN OF FAITH", "WORKERS", "WORKS", "WORSHIP", "WSSSRP", "XTIAN",
    "YOUTH", "ZONAL", "ZONE", "academics", "academy", "accessories", "africa", "agro", "army", "art",
    "associate", "associates", "association", "authority", "auto", "automobile", "bakery", "bank", "bar", "beautyspa",
    "bootcamp", "branch", "broad", "broker", "building", "bureau", "business", "by", "cakes", "capital",
    "care", "cars", "catering", "catholic", "cattle", "cellphone", "center", "centex", "centre", "chamber",
    "chambers", "chops", "church", "cleaning", "clothing", "club", "collection", "college", "comm", "communication",
    "community", "company", "concept", "concepts", "confection", "conservation", "construction", "constructions", "constructs", "consu",
    "consult", "consultants", "consulting", "contractor", "contribution", "cooperative", "corporate", "country", "couture", "creamery",
    "creative", "cuisine", "culture", "cupcake", "custodian", "data", "dealers", "deco", "decor", "decoration",
    "decorations", "design", "designs", "div", "driver", "education", "educational", "empire", "energy", "engineering",
    "ent", "enter", "enterp", "enterprise", "enterprises", "equity", "estate", "etranzact", "event", "exam",
    "expert", "exploration", "express", "farmers", "fashion", "fggc", "fgn", "fidson", "finance", "firs",
    "fish", "food", "foods", "football", "fund", "funds", "furniture", "furnitures", "gallery", "gas",
    "geoscience", "global", "government", "govt", "gratuity", "grills", "grillz", "groundnut", "group", "hair",
    "health", "hireservices", "hospital", "hotel", "house", "hqrs", "ifad", "inc", "industrial", "industry",
    "innovations", "institution", "integrated", "interior", "international", "investment", "ipml", "judicial", "kiddies", "laundry",
    "league", "leasing", "legacy", "license", "lifestyle", "lightning", "limited", "linen", "link", "liquidation",
    "loan", "local", "logistic", "logistics", "ltd", "management", "marble", "marine", "market", "marketing",
    "markets", "media", "medical", "medicare", "meeting", "memorial", "merchant", "merchants", "microfinance", "ministries",
    "ministry", "mixed", "model", "monuments", "motors", "multi", "multiventures", "multivest", "municipal", "network",
    "nigeria", "nitel", "nulge", "odsg", "oil", "organization", "parish", "partners", "path", "pavilion",
    "personal", "petroleum", "pharmaceuticals", "pharmacy", "plaza", "premium", "press", "pri", "primary", "product",
    "production", "products", "project", "projects", "property", "proventures", "pry", "publicity", "publish", "publisher",
    "rccg", "realtor", "rental", "research", "resources", "restaurant", "resturant", "resturants", "retiree", "road",
    "root", "salon", "saloon", "sch", "school", "schools", "science", "secondary", "security", "service",
    "services", "shop", "smallchops", "society", "solution", "solutions", "sons", "spa", "sparepart", "specialist",
    "staff", "stardo", "state", "store", "stores", "studio", "studios", "suit", "suites", "supplies",
    "surveillance", "system", "systems", "tech", "technical", "technology", "textile", "tractor", "trade", "trading",
    "trustee", "uniform", "union", "unipetrol", "united", "universal", "university", "vanguard", "venture", "ventures",
    "wardrob",  "washing", "weavers", "welder", "wholesale", "word", "workers", "workshop", "world",'secrets',"yescredit",
    "worldwide", "youth", "youths"
]
    # Create a DataFrame to store commercial entities/
    corpo2 = pd.DataFrame(columns=indi.columns)
    
    # Rows to remove from individual borrowers
    rows_to_remove = []
    
    # Iterate through individual borrowers to find commercial entities
    for index, row in indi.iterrows():
        # Combine name columns for checking
        name_columns = ['SURNAME', 'FIRSTNAME', 'MIDDLENAME']
        full_name = ' '.join([str(row[col]).lower() for col in name_columns if pd.notna(row[col])])
        
        # Check if the name is a commercial entity
        if is_commercial_entity(full_name, commercial_keywords):
            # Prepare the row for commercial entities
            commercial_row = row.copy()
            
            # Combine names into SURNAME, drop other name columns
            commercial_row['SURNAME'] = f"{row['SURNAME']} {row['FIRSTNAME']} {row['MIDDLENAME']}".strip()
            commercial_row = commercial_row.drop(['FIRSTNAME', 'MIDDLENAME'])
            
            # Append to commercial entities
            corpo2 = pd.concat([corpo2, pd.DataFrame([commercial_row])], ignore_index=True)
            rows_to_remove.append(index)
    
    # Remove identified commercial entities from individual borrowers
    indi = indi.drop(rows_to_remove).reset_index(drop=True)
    
    # Debug prints
    print("Number of commercial entities found:", len(corpo2))
    print("First few commercial entities:")
    print(corpo2.head())
    
    return indi, corpo2

def merge_dataframes(processed_sheets):
    """
    Main merging function with sequential processing
    
    Args:
        processed_sheets (dict): Dictionary of processed DataFrames
    
    Returns:
        tuple: (Individual borrowers DataFrame, Corporate borrowers DataFrame)
    """

    commercial_keywords = [
    "CREDIT", "GVL", "LOA", "POL", "SON", "NIG", "LTD", "AAWUNPCU",'Trader', 'farmer', 'life stock','livestock','chowdeck',
    "ASUU", "AAWUN", "ACADEMI", "ACADEMY", "ACCT", "ADCOMTECH", "ADVISER", "ADVOCATE", "ADVOCATES",'blooms',
    "AFFAIRS", "AGENCIES", "AGENCY", "AGENDA", "AGRIC", "AGRICULTURAL", "AGRICULTURE", "ALLIED", "ALLOCATION", "ALUMINIUM",
    "ANGLICAN", "ANNOINTED",  "ASSEMBLIES", "ASSEMBLY", "ASSETS", "ASSICIATES", "ASSOCIATE", "ASSOCIATES", "ASSOCIATION",
    "ASSOCIATIONS", "ASSOUTION", "AUTO",  "BATHROOM", "BIOMEDICAL", "BOARD", "BOARDS", "BRANCH", "BREAK",
    "BROKERS", "BROTHERS", "BUREAU", "BUSINESS", "BUTCHERS", "CAFETERIA", "CAMP", "CAPITAL", "CARPET",
    "CARPETS", "CARS", "CATERING", "CCTU", "CELLULAR", "CEMENT", "CENTER", "CENTRE", "CHALLENGE", "CHAMBERS",
    "CHANGE", "CHAPTER", "CHARISMATIC", "CHEMICAL", "CHEMICALS", "CHEMISTS", "CHICKEN", "CHURCH", "CITIZEN", "CITIZENS",
    "CLAY", "CLINIC", "CLOSET", "CLUB", "COOPERATIVE", "COEASU", "COHEADS", "COLLECTION", "COLLECTIONS", "COLLEGE",
    "COLOUR",  "COMMERCIAL", "COMMUNICA", "COMMUNICATION", "COMMUNICATIONS", "COMP", "COMPANY", "COMPRHENSIVE", "COMPUTER",
    "COMPUTERS", "CONCEPT", "CONCEPTS", "CONFERENCE", "CONFRENCE", "CONNECT", "CONSORTIUM", "CONST", "CONSTR", "CONSUING",
    "CONSUINGD", "CONSULT", "CONSULTA", "CONSULTANCY", "CONSULTANTS", "CONSULTING", "CONSUMERS", "CONTACT", "CONTRACTOR", "CONTRACTORS",
    "CONTROL", "COOP", "CORP", "CORPORATES", "CORPORATION", "COUNCIL", "COY", "CRADLES", "CREATIONS", "CTV",
    "CURRENT", "DEPARTMENT", "DEPOT", "DEPT", "DESIGN", "DESIGNS", "DEV", "DEVELOPME", "DEVELOPMENT", "DIGITAL",
    "DIOCESE", "DIRECTORATE", "DISABLE", "DISPENSARY", "DIST", "DISTRICT", "DIVERSIFIED", "DIVISION", "DOCKYARD", "DORMANT",
    "DRILL", "DRINK", "DRINKS", "DRIVERS", "EAST", "ECOBANK", "EDUCATION", "ELECRO", "ELECT", "ELECTRICAL",
    "ELECTRICITY", "ELECTRO", "ELECTROMART", "ELECTRONIC", "ELECTRONICS", "EMAGITIONS", "EMBASSY", "EMPLOYEE", "EMPORIUM", "ENERGY",
    "ENGINEERING", "ENGINEERS", "ENT", "ENTERPRIS", "ENTERPRISE", "ENVIROMENT", "EQUIPMENT", "ESTATE", "ESTATES", "EXECUTIVE",
    "EXERCISE", "EXPENDITURE", "EXPORT", "EXPORTS", "FABRIC", "FAMILY", "FARM", "FARMER", "FARMERS", "FARMS",
    "FEDERAL", "FINANCE", "FITNESS", "FOOD", "FOODS", "FORMATIONS", "FORUM", "FOUNDATION", "FOURSQUARE", "FRIENDSHIP",
    "FROZEN", "FURNISHING", "FURNITURE", "FURNITURES", "FUTURE", "GADGET", "GALLERIA", "GARDENS", "GARMENTS", "GENERAL",
    "GEOINFORMATIC", "GEOPLANNERS", "GIFTS", "GLOBA", "GLOBAL", "GLOBE", "GOV", "GOVERNMENT", "GOVT", "GRASSROOTS",
    "GREENSPRINGS", "GROUP", "GROWERS", "GRP", "GYARTAGERE", "HEALTH", "HELP", "HIGH COURT", "HOLDINGS", "HOMES",
    "HOSPITA", "HOSPITAL", "HOSPITALITY", "HOTEL", "HOUSE", "HOUSES", "IMPEX", "IMPORT", "IMPORTS", "IMPRESSION",
    "IND", "INDUSTR", "INDUSTRIE", "INDUSTRIES", "INDUSTRY", "INFINITY", "INFRASTRUCTURE", "INSPECTORATE", "INSPIRATIONAL", "INST",
    "INSTANTE", "INSTITUTE", "INSTITUTUE", "INSURANCE", "INTEGRA", "INTEGRAL", "INTERCONTINENTAL", "INTERNAL", "INTERNATIONA", "INTERNATIONAL",
    "INTL", "INV", "INVESMENT", "INVESMENTS", "INVESTMEN", "INVESTMENT", "INVESTMENTS", "INVESTMESTS", "JOINT", "KAD",
    "KONSULT", "L E A", "LEA", "LGE A", "LAB", "LABORATORIES", "LABORATORY", "LAPTOP", "LEASING", "LEGACY",
    "LEGAL", "LEISURE", "LGA", "LGEA", "LIBRARY",  "LIMI", "LIMIT", "LIMITE", "LIMITED",
    "LIMTED", "LIVING", "LOANS", "LOCAL", "LOGISTICS", "LOKOJA", "MACRO", "MAGER", "MANAGEMENT", "MANAGERS",
    "MANUFACT", "MANUFACTURE", "MANUFACTURERS", "MANUFACTURING", "MARBLE", "MARKET", "MARKETING", "MASHIDIMAMI", "MATHNIC", "MEDIA",
    "MEDICAL", "MERCHANDISE", "MGMT", "MICRO", "MICROFINANCE", "MILLENNIUM", "MINERAL", "MINERALS", "MINING", "MINISTRIES",
    "MINISTRY", "MINTING", "MISSION", "MOBILE", "MODERN", "MOSQUE", "MOTORS", "MPCS", "MULTI", "MULTIPURPOSE",
    "MULTITECH", "MUSICIANS", "Markert", "Marketers", "N U T",  "NATIONAL", "NETWORK", "NIGERIA", "NOODLES",
    "NORTH", "NURSERY", "NUT", "OCEAN", "OFFICE", "OFFSHORE", "OFPHYSICAL", "OGSG", "OPINION", "ORG",'cup',
    "ORGANISATION", "ORGANIZATION", "ORIENTAL", "OUTLOOK", "OVERHEAD", "PAINT", "PARTNER", "PARTS", "PAVILION", "PENSION",
     "PERFORMANCE", "PERFORMING", "PETROCHEMICALS", "PETROLEUM", "PETROLSEAL", "PETROSERVE", "PFA", "PHARMA", "PHARMACEUTICAL",
    "PHYSIOTHERAPY", "PILLAR", "PLACE", "PLASTIC", "PLAZA", "PLC", "POINT", "POLITICAL", "POLYMALT", "POLYMER",
    "POLYTECHNIC", "POULTRY", "POVERTY", "PRECID", "PRIMARY", "PRINT", "PRINTING", "PRINTS", "PRIVATE", "PROD",
    "PRODUCT", "PRODUCTIONS", "PRODUCTS", "PROFILE", "PROJECT", "PROJECTS", "PROPERTIES", "PROPERTY", "PROVINCE", "PRY",
    "PUBLIC", "PUBLICATION",  "PYRAMID", "QUANTITEQUE", "RCCG", "RATTAWU", "REALITIES", "REALTOR", "REALTORS",
    "RECIPE", "REDUCTION", "REFUGE", "REGISTRAR", "REHOBOTH", "REMITTANCE", "REMMT", "RENTAL", "RESEARCH", "RESORT",
    "RESORTS", "RESOURCE", "RESOURCES", "RESOURSES", "RESTAURANT", "RESTURANT", "REVENUE", "ROCKS", "ROOFING", "RURAL",
    "Relations", "Resources", "Restructure", "SADP", "SEPA", "SGARI", "SAFETY", "SALES", "SALON",
    "SANCTUARY", "SAVINGS", "SAVIOURS", "SCH", "SCHEME", "SCHEMES", "SCHOOL", "SCHOOLS", "SCIENTIFIC", "SECODARY",
    "SECONDARY", "SECRETARIAT", "SECURITIES", "SECURITY", "SEEDS", "SELLER", "SELLERS", "SERV", "SERVANT", "SERVANTS",
    "SERVI", "SERVICES", "SHARES", "SHIPPING", "SOCEITY", "SOCIETY", "SOLICITOR", "SOLICITORS",
    "SOLID", "SOLUTION", "SOLUTIONS", "SONS", "SOTER", "SOUND", "SOUTH", "SPARE", "SPECIAL", "SPIRITUAL",
    "SPORT", "SPORTS", "SPRAYING", "SSANIP", "STANDARD", "STATE", "STATION", "STEEL", "STOC", "STOCK",
    "STORE", "STORES", "STRATEGIC", "STRUCTURAL", "STUDENTS", "SUBSCRIPTION", "SUBSTANCE", "SUITES", "SUPER", "SUPPLY",
    "SUPPY", "SURPRISES", "SURVEILLANCE", "SURVEY", "SYSTEM", "SYSTEMS", "TABERNACLE", "TABLE", "TAX", "TEC",
    "TECHNICAL", "TECHNO", "TECHNOLOGIE", "TECHNOLOGIES", "TELECOMS", "TELEVISION", "TEXTILES", "THEME", "THINKING", "TIMELESS",
    "TODDLERS", "TOTAL", "TOURIST", "TRADE", "TRADER", "TRADERS", "TRADING", "TRAINING", "TRANS", "TRAVEL",
    "TRAVELS", "TRUCK", "TRUCKS", "Traditional",  "UNIMAID", "UNION", "UNIONS", "UNIV", "UNIVERSITY",
    "USERS", "VALLEY", "VENT", "VENTURE", "VENTURES", "VESSEL", "VESSELS",  "WA", "WMPCS",
    "WARD",  "WIRELESS", "WOMEN", "WOMEN OF FAITH", "WORKERS", "WORKS", "WORSHIP", "WSSSRP", "XTIAN",
    "YOUTH", "ZONAL", "ZONE", "academics", "academy", "accessories", "africa", "agro", "army", "art",
    "associate", "associates", "association", "authority", "auto", "automobile", "bakery", "bank", "bar", "beautyspa",
    "bootcamp", "branch", "broad", "broker", "building", "bureau", "business", "by", "cakes", "capital",
    "care", "cars", "catering", "catholic", "cattle", "cellphone", "center", "centex", "centre", "chamber",
    "chambers", "chops", "church", "cleaning", "clothing", "club", "collection", "college", "comm", "communication",
    "community", "company", "concept", "concepts", "confection", "conservation", "construction", "constructions", "constructs", "consu",
    "consult", "consultants", "consulting", "contractor", "contribution", "cooperative", "corporate", "country", "couture", "creamery",
    "creative", "cuisine", "culture", "cupcake", "custodian", "data", "dealers", "deco", "decor", "decoration",
    "decorations", "design", "designs", "div", "driver", "education", "educational", "empire", "energy", "engineering",
    "ent", "enter", "enterp", "enterprise", "enterprises", "equity", "estate", "etranzact", "event", "exam",
    "expert", "exploration", "express", "farmers", "fashion", "fggc", "fgn", "fidson", "finance", "firs",
    "fish", "food", "foods", "football", "fund", "funds", "furniture", "furnitures", "gallery", "gas",
    "geoscience", "global", "government", "govt", "gratuity", "grills", "grillz", "groundnut", "group", "hair",
    "health", "hireservices", "hospital", "hotel", "house", "hqrs", "ifad", "inc", "industrial", "industry",
    "innovations", "institution", "integrated", "interior", "international", "investment", "ipml", "judicial", "kiddies", "laundry",
    "league", "leasing", "legacy", "license", "lifestyle", "lightning", "limited", "linen", "link", "liquidation",
    "loan", "local", "logistic", "logistics", "ltd", "management", "marble", "marine", "market", "marketing",
    "markets", "media", "medical", "medicare", "meeting", "memorial", "merchant", "merchants", "microfinance", "ministries",
    "ministry", "mixed", "model", "monuments", "motors", "multi", "multiventures", "multivest", "municipal", "network",
    "nigeria", "nitel", "nulge", "odsg", "oil", "organization", "parish", "partners", "path", "pavilion",
    "personal", "petroleum", "pharmaceuticals", "pharmacy", "plaza", "premium", "press", "pri", "primary", "product",
    "production", "products", "project", "projects", "property", "proventures", "pry", "publicity", "publish", "publisher",
    "rccg", "realtor", "rental", "research", "resources", "restaurant", "resturant", "resturants", "retiree", "road",
    "root", "salon", "saloon", "sch", "school", "schools", "science", "secondary", "security", "service",
    "services", "shop", "smallchops", "society", "solution", "solutions", "sons", "spa", "sparepart", "specialist",
    "staff", "stardo", "state", "store", "stores", "studio", "studios", "suit", "suites", "supplies",
    "surveillance", "system", "systems", "tech", "technical", "technology", "textile", "tractor", "trade", "trading",
    "trustee", "uniform", "union", "unipetrol", "united", "universal", "university", "vanguard", "venture", "ventures",
    "wardrob",  "washing", "weavers", "welder", "wholesale", "word", "workers", "workshop", "world",'secrets',"yescredit",
    "worldwide", "youth", "youths"
]
    # Extract DataFrames from processed sheets
    consu = processed_sheets.get('individualborrowertemplate', pd.DataFrame())
    comm = processed_sheets.get('corporateborrowertemplate', pd.DataFrame())
    credit = processed_sheets.get('creditinformation', pd.DataFrame())
    guar = processed_sheets.get('guarantorsinformation', pd.DataFrame())
    prin = processed_sheets.get('principalofficerstemplate', pd.DataFrame())

    indi = merge_individual_borrowers(consu, credit, guar)
    corpo = merge_corporate_borrowers(comm, credit, prin)

        # Print merged corporate borrowers
    print("\n=== MERGED CORPORATE BORROWERS ===")
    print(corpo.head()) 

    indi = indi.applymap(lambda x: None if str(x).strip().lower() in ['none', 'nan', 'null', 'nill', 'nil'] else x)
    corpo = corpo.applymap(lambda x: None if str(x).strip().lower() in ['none', 'nan', 'null', 'nill', 'nil'] else x)
    
    #Step 3: Split commercial entities from individual borrowers
    indi, corpo2 = split_commercial_entities(indi)


    print("\n=== SHEET DATA AFTER MERGING ===")
    print("Number of rows:", len(indi))
    print("First few rows:")
    print(indi.head())

    print("Number of rows:", len(corpo))
    print("First few rows:")
    print(corpo.head())    # Debug prints
    print("Original corporate borrowers:", len(corpo))
    print("Commercial entities to add:", len(corpo2))
    
    print("Number of rows:", len(corpo2))
    print("First few rows:")
    print(corpo2.head())
    print("================================")


    # Step 4: Rename commercial entities before combining
    if not corpo2.empty:
        # Rename corpo2 columns to match corporate borrower template
        corpo2 = rename_columns(corpo2, ConsuToComm.copy())
        
        # Debug statement to show corpo2 details before concatenation
        print("Number of commercial entities:", len(corpo2))
        print("First few rows of corpo2:")
        print(corpo2.head())
        
        # Combine commercial entities with existing corporate borrowers
        corpo = pd.concat([corpo, corpo2], ignore_index=True)
        
        # Debug statement to confirm addition
        print("\nAfter Adding Commercial Entities:")
        print("Total corporate borrowers:", len(corpo))
        print("Columns in final corpo:", corpo.columns)
        print("First few rows after addition:")
        print(corpo.head())
        


        # Additional check to verify commercial entities were added
        commercial_entities_in_corpo = corpo[
            corpo['BUSINESSNAME'].apply(
                lambda x: any(keyword in str(x).lower() for keyword in commercial_keywords)
            )
        ]
        print("\nCommercial Entities in Final Corporate Borrowers:")
        print("Number of commercial entities:", len(commercial_entities_in_corpo))
        print("First few commercial entities:")
        print(commercial_entities_in_corpo.head())
    
    return indi, corpo
 
def rename_columns(df, column_mapping):
    """
    Rename columns based on a mapping dictionary
    
    Args:
        df (pd.DataFrame): Input DataFrame
        column_mapping (dict): Mapping of column names
    
    Returns:
        pd.DataFrame: DataFrame with renamed columns
    """
    try:
        # Print original columns before renaming
        print("Original columns before renaming:", list(df.columns))
        print("Mapping being used:", column_mapping)

        # Rename columns that match the mapping
        for column in list(df.columns):  # Use list() to create a copy of columns
            for mapped_column, alt_names in column_mapping.items():
                if column in alt_names or column.lower() in alt_names or column.upper() in alt_names:
                    df.rename(columns={column: mapped_column}, inplace=True)
                    print(f"Renamed {column} to {mapped_column}")
                    break
        
        # Print columns after initial renaming
        print("Columns after renaming:", list(df.columns))

        # Add missing columns from the dictionary
        for mapped_column in column_mapping.keys():
            if mapped_column not in df.columns:
                df[mapped_column] = None
                print(f"Added missing column: {mapped_column}")
        
        # Print columns before final reordering
        print("Columns before reordering:", list(df.columns))

        # Reorder the columns based on the keys in the dictionary
        df = df[list(column_mapping.keys())]
        
        # Print final columns
        print("Final columns after reordering:", list(df.columns))

        return df
    except Exception as e:
        print(f"Error in rename_columns: {e}")
        traceback.print_exc()
        return df

def modify_middle_names(df):
    """Keep only the first name in the specified middle name columns."""
    middle_name_columns = [
        'MIDDLENAME',
        'SPOUSEMIDDLENAME',
        'GUARANTORMIDDLENAME',
        'PRINCIPALOFFICER1MIDDLENAME',
        'PRINCIPALOFFICER2MIDDLENAME'
    ]
    
    for col in middle_name_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: str(x).split()[0] if pd.notna(x) and str(x).strip() else '')
    
    return df

def trim_strings_to_59(df):
    """
    Trim all string values in the DataFrame to 59 characters maximum
    
    Args:
        df (pd.DataFrame): Input DataFrame
        
    Returns:
        pd.DataFrame: DataFrame with all string values trimmed to 59 characters
    """
    # Define the trimming function
    def trim_string(s):
        if isinstance(s, str) and len(s) > 59:
            return s[:58]  # Trim to 58 characters as requested
        return s
    
    # Apply the function to all elements in the DataFrame
    print("\n=== TRIMMING STRING VALUES TO 59 CHARACTERS ===")
    df = df.applymap(trim_string)
    print("String trimming completed")
    
    return df

def upload_file(request):
    if request.method == 'POST':
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']
            # Get original filename without extension
            original_filename = os.path.splitext(uploaded_file.name)[0]

            fs = FileSystemStorage()
            filename = fs.save(uploaded_file.name, uploaded_file)
            file_path = os.path.join(settings.MEDIA_ROOT, filename)
          
            try:
                # Read all sheets into a dictionary of DataFrames
                xds = pd.read_excel(file_path, sheet_name=None, na_filter=False, dtype=object)

                 # Store column counts and processing stats
                processing_stats = []

                # Convert all sheets to string type immediately after reading
                for sheet_name, df in xds.items():
                    initial_records = len(df)

                     # Record initial column count
                    processing_stats.append({
                        'sheet_name': sheet_name,
                        'initial_columns': len(df.columns),
                       'initial_records': initial_records,  # Track raw row count
                        'processed_columns': None,
                        'valid_records': 0  # To be updated after column renaming
                    })

                    
                    print(f"\nConverting sheet to string: {sheet_name}")
                    # Convert all columns to string
                    for col in df.columns:
                        df[col] = df[col].astype(str)
                        # Replace 'nan' values with empty string
                        df[col] = df[col].replace({'nan': '', 'None': '', 'NaN': ''})
                    xds[sheet_name] = df

                # Print initial sheet information
                print("\n=== INITIAL SHEET COUNT ===")
                print(f"Number of sheets in uploaded file: {len(xds)}")
                print("Sheets found:")
                for sheet_name in xds.keys():
                    print(f"- {sheet_name}")
                print("========================")

                # Ensure all required sheets exist
                processed_sheets = ensure_all_sheets_exist(xds)
                
                # Print processed sheet information
                print("\n=== PROCESSED SHEET COUNT ===")
                print(f"Number of sheets after processing: {len(processed_sheets)}")
                print("Final sheets:")
                for sheet_name in processed_sheets.keys():
                    print(f"- {sheet_name}")
                print("========================")

                # Process each sheet
                for sheet_name, sheet_data in xds.items():
                    cleaned_name = clean_sheet_name(sheet_name)
                    # Process sheet
                    cleaned_df = sheet_data.copy()
                    for column in cleaned_df.columns:
                        if cleaned_df[column].dtype == object:
                            cleaned_df[column] = cleaned_df[column].apply(
                                lambda x: str(x)[:52] if isinstance(x, str) else x
                            )
                    cleaned_df.replace('N/A', '', inplace=True)
# Fix column cleaning sequence
                    cleaned_df.columns = [
                        str(col).upper().strip()  # Ensure column names are strings first
                        for col in cleaned_df.columns
                    ]
                    cleaned_df.columns = [remove_special_characters(col) for col in cleaned_df.columns]

                    # Apply appropriate mapping based on sheet name
                    if cleaned_name == 'individualborrowertemplate':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, consu_mapping)
                    elif cleaned_name == 'corporateborrowertemplate':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, comm_mapping)
                    elif cleaned_name == 'principalofficerstemplate':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, prin_mapping)
                    elif cleaned_name == 'creditinformation':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, credit_mapping)
                    elif cleaned_name == 'guarantorsinformation':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, guar_mapping)

                    for stat in processing_stats:
                        if stat['sheet_name'] == sheet_name:
                            if cleaned_name == 'individualborrowertemplate' and 'CUSTOMERID' in cleaned_df.columns:
                                stat['valid_records'] = cleaned_df['CUSTOMERID'].astype(str).ne('').sum()
                            elif cleaned_name == 'corporateborrowertemplate' and 'CUSTOMERID' in cleaned_df.columns:
                                stat['valid_records'] = cleaned_df['CUSTOMERID'].astype(str).ne('').sum()
                            elif cleaned_name == 'creditinformation' and 'CUSTOMERID' in cleaned_df.columns:
                                stat['valid_records'] = cleaned_df['CUSTOMERID'].astype(str).ne('').sum()
                            elif cleaned_name == 'principalofficerstemplate' and 'CUSTOMERID' in cleaned_df.columns:
                                stat['valid_records'] = cleaned_df['CUSTOMERID'].astype(str).ne('').sum()
                            elif cleaned_name == 'guarantorsinformation' and 'CUSTOMERSACCOUNTNUMBER' in cleaned_df.columns:
                                stat['valid_records'] = cleaned_df['CUSTOMERSACCOUNTNUMBER'].astype(str).ne('').sum()
                            break

                    # Apply processing steps
                    cleaned_df = process_dates(cleaned_df)
                    cleaned_df = process_special_characters(cleaned_df) 
                    cleaned_df = process_names(cleaned_df)
                    cleaned_df = process_nationality(cleaned_df)
                    cleaned_df = process_gender(cleaned_df)
                    cleaned_df = process_states(cleaned_df)
                    cleaned_df = process_marital_status(cleaned_df)
                    cleaned_df = process_borrower_type(cleaned_df)
                    cleaned_df = process_employment_status(cleaned_df)
                    cleaned_df = process_phone_columns(cleaned_df)
                    cleaned_df = process_title(cleaned_df)
                    cleaned_df = process_account_status(cleaned_df)
                    cleaned_df = process_loan_type(cleaned_df)
                    cleaned_df = process_currency(cleaned_df)
                    cleaned_df = process_repayment(cleaned_df)
                    cleaned_df = process_classification(cleaned_df)
                    cleaned_df = process_collateral_type(cleaned_df)
                    cleaned_df = process_loan_tenor(cleaned_df)
                    cleaned_df = clear_previous_info_columns(cleaned_df)
                    cleaned_df = process_numeric_columns(cleaned_df)
                    cleaned_df = fill_data_column(cleaned_df)
                    cleaned_df = fill_depend_column(cleaned_df)
                    cleaned_df = process_identity_numbers(cleaned_df)
                    cleaned_df = process_passport_number(cleaned_df)
                    cleaned_df = process_business_id(cleaned_df)
                    cleaned_df = process_bvn_number(cleaned_df)
                    cleaned_df = process_occu(cleaned_df)
                    cleaned_df = process_DriversLicense(cleaned_df)
                    cleaned_df = process_otherid(cleaned_df)

   #---------------------------------------------------------ABANDONED FOR NOW------------------------------------------                 
                    # cleaned_df = process_business_sector(cleaned_df)
    #--------------------------------------------------------------------------------------------------------------------                
                    for stat in processing_stats:
                        if stat['sheet_name'] == sheet_name:
                            stat['processed_columns'] = len(cleaned_df.columns)
                            break

                    processed_sheets[cleaned_name] = cleaned_df

                # Merge processed sheets
                indi, corpo = merge_dataframes(processed_sheets)

                # Now modify middle names after merging
                indi = modify_middle_names(indi)
                corpo = modify_middle_names(corpo)

                # Remove duplicates from merged DataFrames
                indi = remove_duplicates(indi)
                corpo = remove_duplicates(corpo)

                # Trim strings to 59 characters
                indi = trim_strings_to_59(indi)
                corpo = trim_strings_to_59(corpo)

                total_individual_records = len(indi) if not indi.empty else 0
                total_corporate_records = len(corpo) if not corpo.empty else 0

                # Generate unique filenames with original filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                indi_output_filename = f"{original_filename}_individual_borrowers_{timestamp}.xlsx"
                corpo_output_filename = f"{original_filename}_corporate_borrowers_{timestamp}.xlsx"
                full_output_filename = f"{original_filename}_processed_{timestamp}.xlsx"


# Create excel directory structure
                excel_dir = os.path.join(settings.MEDIA_ROOT, 'excel')
                excel_individual_dir = os.path.join(excel_dir, 'individual')
                excel_corporate_dir = os.path.join(excel_dir, 'corporate')
                excel_full_dir = os.path.join(excel_dir, 'full')
                os.makedirs(excel_individual_dir, exist_ok=True)
                os.makedirs(excel_corporate_dir, exist_ok=True)
                os.makedirs(excel_full_dir, exist_ok=True)

                # Save individual borrowers merged file
                indi_excel_path = os.path.join(excel_individual_dir, indi_output_filename)
                indi.to_excel(indi_excel_path, index=False)
                indi_processed_file_url = fs.url(os.path.join('excel', 'individual', indi_output_filename))

                # Save corporate borrowers merged file
                corpo_excel_path = os.path.join(excel_corporate_dir, corpo_output_filename)
                corpo.to_excel(corpo_excel_path, index=False)
                corpo_processed_file_url = fs.url(os.path.join('excel', 'corporate', corpo_output_filename))

                # Save full processed file with all sheets
                full_excel_path = os.path.join(excel_full_dir, full_output_filename)
                with pd.ExcelWriter(full_excel_path, engine='openpyxl') as writer:
                    # Save individual processed sheets
                    for sheet_name, df in processed_sheets.items():
                        print(f"Saving sheet: {sheet_name}")
                        df.to_excel(writer, sheet_name=sheet_name, index=False)

                    # Save merged sheets
                    if not indi.empty:
                        indi.to_excel(writer, sheet_name='Merged_Individual_Borrowers', index=False)
                    if not corpo.empty:
                        corpo.to_excel(writer, sheet_name='Merged_Corporate_Borrowers', index=False)
                full_processed_file_url = fs.url(os.path.join('excel', 'full', full_output_filename))
    # Add TXT version saving
                indi_txt_filename = f"{original_filename}_individual_borrowers_{timestamp}.txt"
                corpo_txt_filename = f"{original_filename}_corporate_borrowers_{timestamp}.txt"
                full_txt_filename = f"{original_filename}_processed_{timestamp}.txt"

# Add this before file processing
                txt_dir = os.path.join(settings.MEDIA_ROOT, 'txt')
                os.makedirs(txt_dir, exist_ok=True)  # Create txt directory if not exists
                # Create subdirectories
                txt_individual_dir = os.path.join(txt_dir, 'individual')
                txt_corporate_dir = os.path.join(txt_dir, 'corporate')
                txt_full_dir = os.path.join(txt_dir, 'full')
                os.makedirs(txt_individual_dir, exist_ok=True)
                os.makedirs(txt_corporate_dir, exist_ok=True)
                os.makedirs(txt_full_dir, exist_ok=True)
                # Save individual borrowers TXT
                indi_txt_path = os.path.join(txt_individual_dir, indi_txt_filename)
                indi.to_csv(indi_txt_path, sep='\t', index=False, encoding='utf-8')

                # Save corporate borrowers TXT
                corpo_txt_path = os.path.join(txt_corporate_dir, corpo_txt_filename)
                corpo.to_csv(corpo_txt_path, sep='\t', index=False, encoding='utf-8')

                # Save full processed TXT (example - would need custom implementation)
                full_txt_path = os.path.join(txt_full_dir, full_txt_filename)
                with open(full_txt_path, 'w', encoding='utf-8') as f:
                    for sheet_name, df in processed_sheets.items():
                        f.write(f"=== {sheet_name} ===\n")
                        df.to_csv(f, sep='\t', index=False)
                        f.write("\n\n")
                # Add TXT URLs to context
                indi_txt_url = fs.url(os.path.join('txt', 'individual', indi_txt_filename))
                corpo_txt_url = fs.url(os.path.join('txt', 'corporate', corpo_txt_filename)) 
                full_txt_url = fs.url(os.path.join('txt', 'full', full_txt_filename))
                
                return render(request, 'upload.html', {
                    'form': form,
                    'success_message': 'File processed and merged successfully!',
                    'processing_stats': processing_stats,
                    'total_individual': total_individual_records,
                    'total_corporate': total_corporate_records,
                    'individual_download_url': indi_processed_file_url,
                    'corporate_download_url': corpo_processed_file_url,
                    'full_download_url': full_processed_file_url,
                    'individual_txt_url': indi_txt_url,
                    'corporate_txt_url': corpo_txt_url,
                    'full_txt_url': full_txt_url
                })

            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                return render(request, 'upload.html', {
                    'form': form,
                    'error_message': f'Error Details:\n{error_details}'
                })
                #  return render(request, 'upload.html', {
                #     'form': form,
                #     'error_message': f'Error processing file: {str(e)}'
                # })
            finally:
                # Clean up the uploaded file
                if os.path.exists(file_path):
                    os.remove(file_path)

    else:
        form = ExcelUploadForm()
    
    return render(request, 'upload.html', {'form': form})
