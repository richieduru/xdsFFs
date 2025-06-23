import os
import pandas as pd
import re
import dateparser
import numpy as np
from datetime import datetime, timedelta
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import ExcelUploadForm
from .map import consu_mapping, comm_mapping, guar_mapping, credit_mapping, prin_mapping,Gender_dict,Country_dict,state_dict,Marital_dict,Borrower_dict,Employer_dict,Title_dict,Occu_dict,AccountStatus_dict,Loan_dict,Repayment_dict,Currency_dict,Classification_dict,Collateraltype_dict,Positioninbusiness_dict,ConsuToComm,CommToConsu, commercial_keywords,consumer_merged_mapping,commercial_merged_mapping
from .filename_utils import generate_filename, generate_fallback_filename
from rapidfuzz import fuzz, process
from typing import Union, Optional
from word2number import w2n
from datetime import datetime
import traceback
from django.views.decorators.csrf import csrf_exempt
import json


def extract_subscriber_alias_from_filename(filename):
    """
    Extract subscriber alias from filename by removing date patterns
    
    Args:
        filename (str): The filename to extract subscriber alias from
        
    Returns:
        str: The subscriber alias without date information
    """
    if not filename:
        return filename
    
    # Remove file extension
    base_filename = filename
    if '.' in base_filename:
        base_filename = base_filename.rsplit('.', 1)[0]
    
    # Remove common date patterns
    # Pattern 1: Remove YYYY_MM_DD format
    base_filename = re.sub(r'[_\s]*\d{4}[_\s]*\d{1,2}[_\s]*\d{1,2}[_\s]*', '', base_filename)
    
    # Pattern 2: Remove Month_Year or Year_Month patterns
    month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                   'july', 'august', 'september', 'october', 'november', 'december',
                   'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec']
    
    for month_name in month_names:
        # Remove month_year pattern (e.g., "may 2024", "may_2024")
        pattern = rf'[_\s]*{month_name}[_\s]*\d{{4}}[_\s]*'
        base_filename = re.sub(pattern, '', base_filename, flags=re.IGNORECASE)
        
        # Remove year_month pattern (e.g., "2024 may", "2024_may")
        pattern = rf'[_\s]*\d{{4}}[_\s]*{month_name}[_\s]*'
        base_filename = re.sub(pattern, '', base_filename, flags=re.IGNORECASE)
    
    # Clean up any trailing/leading spaces or underscores
    base_filename = base_filename.strip(' _')
    
    # If nothing left, return original filename without extension
    if not base_filename:
        return filename.rsplit('.', 1)[0] if '.' in filename else filename
    
    return base_filename


def extract_date_from_filename(filename):
    """
    Extract month and year from filename in various formats
    
    Args:
        filename (str): The filename to extract date from
        
    Returns:
        tuple: (month, year) as integers, or (None, None) if no date found
    """
    if not filename:
        return None, None
    
    # Remove file extension
    base_filename = filename.lower()
    if '.' in base_filename:
        base_filename = base_filename.rsplit('.', 1)[0]
    
    # Pattern 1: YYYY_MM_DD format (e.g., alekun_2024_03_31)
    pattern1 = r'(\d{4})_(\d{1,2})_(\d{1,2})'
    match1 = re.search(pattern1, base_filename)
    if match1:
        year, month, day = match1.groups()
        return int(month), int(year)
    
    # Pattern 2: Month_Year format (e.g., alekun_may_2024, alekun_march_2024)
    month_names = {
        'january': 1, 'jan': 1,
        'february': 2, 'feb': 2,
        'march': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'may': 5,
        'june': 6, 'jun': 6,
        'july': 7, 'jul': 7,
        'august': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12
    }
    
    # Look for month name followed by year
    for month_name, month_num in month_names.items():
        pattern2 = rf'{month_name}[_\s]*?(\d{{4}})'
        match2 = re.search(pattern2, base_filename)
        if match2:
            year = match2.group(1)
            return month_num, int(year)
    
    # Pattern 3: Year_Month format (e.g., alekun_2024_may)
    for month_name, month_num in month_names.items():
        pattern3 = rf'(\d{{4}})[_\s]*?{month_name}'
        match3 = re.search(pattern3, base_filename)
        if match3:
            year = match3.group(1)
            return month_num, int(year)
    
    # No date pattern found
    return None, None


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
    
    # First check if we have merged sheets
    has_merged_sheets = False
    for original_name in xds.keys():
        cleaned_name = clean_sheet_name(original_name)
        if cleaned_name in ['consumermerged', 'commercialmerged']:
            has_merged_sheets = True
            print(f"? Found merged sheet: {original_name}")
            processed_sheets[cleaned_name] = xds[original_name]
            existing_sheets.append(original_name)
    
    # If we have merged sheets, skip generating missing sheets
    if has_merged_sheets:
        print("\n=== MERGED SHEETS DETECTED ===")
        print("Skipping generation of missing sheets as merged sheets are present")
        return processed_sheets
    
    # Regular sheet processing if no merged sheets found
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

def preprocess_tenor_from_headers(df):
    """
    Checks column headers for time units (e.g., 'Loan Tenor (Months)')
    and converts the data in that column to days. This version handles
    days, weeks, months, and years.
    """
    df_copy = df.copy()
    
    # --- UPDATED: Comprehensive dictionary for all units ---
    header_unit_multipliers = {
        # Days
        'days': 1, 'day': 1, 'd': 1, 'dys': 1,
        # Weeks
        'weeks': 7, 'week': 7, 'w': 7,
        # Months
        'months': 30, 'month': 30, 'mnth': 30, 'mth': 30, 
        'mths': 30, 'mnths': 30, 'mons': 30, 'm': 30,
        # Years
        'years': 365, 'year': 365, 'y': 365, 'yr': 365, 'yrs': 365,
    }

    # Regex to find any of the units in the dictionary, ignoring case
    # This looks for the unit as a whole word
    pattern = r'\b(' + '|'.join(header_unit_multipliers.keys()) + r')\b'

    for col in df_copy.columns:
        # Search for a unit in the column name (case-insensitive)
        match = re.search(pattern, col, re.IGNORECASE)
        
        if match:
            unit_found = match.group(0).lower()
            multiplier = header_unit_multipliers[unit_found]
            
            print(f"Found unit '{unit_found}' in header '{col}'. Applying multiplier: {multiplier}")
            
            # Apply the multiplier to the column.
            # pd.to_numeric converts numbers; errors='coerce' handles non-numbers gracefully.
            # .fillna(0) replaces any conversion errors with 0.
            numeric_col = pd.to_numeric(df_copy[col], errors='coerce').fillna(0).astype(int)
            df_copy[col] = numeric_col * multiplier
    
    return df_copy

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
    if not isinstance(name, str):
        return name
    
    titles = [
        'Miss', 'Mrs', 'Rev', 'Dr', 'Mr', 'MS', 'CAPT','pastor',
        'COL', 'LADY', 'MAJ', 'PST', 'PROF', 'REV', 'SGT',
        'SIR', 'HE', 'JUDG', 'CHF', 'ALHJ', 'APOS', 'CDR', 'ALH', 'Alh',
        'BISH', 'FLT', 'BARR', 'MGEN', 'GEN', 'HON', 'ENGR', 'LT', 'AND', 'and',
        'PASTOR', 'PAST', 'PST', 'ALHAJI', 'ALH', 'ALH.', 'ALHAJ', 'ALHADJI', 'ALHAJJI', 'ALHAJ.', 'ALHADJ', 'ALHADJ.',
        'PASTOR.', 'PASTOR', 'PAST.', 'PST.', 'REV.', 'REV', 'DR.', 'MR.', 'MRS.', 'MS.'
    ]
    
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
    missing_values = ["", "None", "NaN", "null", "N/A", "n/a", "na", "NA", "#N/A", "?", "missing",'N.A']
    
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
        if serial_number <= 0 or serial_number > 2958465:
            return None  # Invalid range for Excel date serial numbers
        
        # Excel serial date base is 1899-12-30
        base_date = datetime(1899, 12, 30)
        calculated_date = base_date + timedelta(days=int(serial_number))
        if calculated_date.year < 1900:
            return None
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
            if date.year < 1900:
                return None
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
            if date.year < 1900:
                return None
            return f"{date.year:04d}{date.month:02d}{date.day:02d}"
        except ValueError:
            continue
    
    # If all explicit formats fail, try dateparser as a fallback
    try:
        date = dateparser.parse(str(date_string))
        if date:
            if date.year < 1900:
                return None
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

def clean_name_preserving_special_chars(text):
    """Clean names by replacing hyphens with spaces and removing all other special characters"""
    if not text:
        return ''
    
    # Convert to string if not already
    text = str(text)
    
    # First replace hyphens with spaces
    text = text.replace('-', '').replace("'", '')
    
    # Remove all other special characters
    text = re.sub(r'[^a-zA-Z0-9&]', ' ', text)
    
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
            
            # Remove titles and clean names while preserving special characters
            for col in name_columns:
                df[col] = df[col].apply(remove_titles).apply(clean_name_preserving_special_chars)
            
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
                    df[col] = df[col].apply(remove_titles).apply(clean_name_preserving_special_chars)
    
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

    # Collect columns to drop due to conflicts
    columns_to_drop = []

    # Iterate over the columns and rename them
    for column in list(df.columns):  # Use list to avoid issues when dropping columns
        found_match = False
        for mapped_column, alt_names in mapping.items():
            # Check if the key has been used
            if used_keys_mapping[mapped_column] is not None:
                continue

            # Check if the column name is in alt_names
            if column.lower() in alt_names or column.upper() in alt_names or column == mapped_column:
                # Check for key conflict: if mapped_column already exists in df.columns (and is not the current column)
                if mapped_column in df.columns and column != mapped_column:
                    columns_to_drop.append(column)
                    print(f"Column {column} dropped due to key conflict with {mapped_column}.")
                else:
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
                # Check for key conflict: if fuzzy_match_result already exists in df.columns (and is not the current column)
                if fuzzy_match_result in df.columns and column != fuzzy_match_result:
                    columns_to_drop.append(column)
                    print(f"Column {column} dropped due to key conflict with {fuzzy_match_result} (fuzzy match).")
                elif used_keys_mapping[fuzzy_match_result] is None:
                    df.rename(columns={column: fuzzy_match_result}, inplace=True)
                    renamed_columns.add(fuzzy_match_result)
                    used_keys_mapping[fuzzy_match_result] = column
                    print(f"Fuzzy matched {column} to {fuzzy_match_result}")
                else:
                    columns_to_drop.append(column)
                    print(f"Column {column} dropped due to key conflict (fuzzy match already used).")

    # Drop all columns that were marked for dropping
    if columns_to_drop:
        df.drop(columns=columns_to_drop, inplace=True, errors='ignore')

    # Drop duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]

    # Add columns for keys that were not mapped
    new_columns = {key: None for key, used_column in used_keys_mapping.items() if used_column is None}
    df = pd.concat([df, pd.DataFrame(new_columns, index=df.index)], axis=1)

    # Ensure all mapping keys are present as columns
    for key in mapping.keys():
        if key not in df.columns:
            df[key] = None

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
        'PRINCIPALOFFICER1COUNTRY',
        'PRINCIPALOFFICER2COUNTRY',
        'GUARANTORPRIMARYADDRESSCOUNTRY',
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
        'SURNAME',
        'FIRSTNAME',
        'MIDDLENAME',
        'INDIVIDUALGUARANTORSURNAME',
        'INDIVIDUALGUARANTORFIRSTNAME',
        'INDIVIDUALGUARANTORMIDDLENAME',
        'PRINCIPALOFFICERSURNAME',
        'PRINCIPALOFFICERFIRSTNAME',
        'PRINCIPALOFFICERMIDDLENAME'
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
        'COLLATERALDETAILS',
        'BUSINESSNAME',
        'BUSINESSCATEGORY'
    ]
    
    # Account number columns that should preserve '/' and '-'
    account_number_columns = [
        'ACCOUNTNUMBER',
        'CUSTOMERSACCOUNTNUMBER'
    ]

    # Find processable columns (those not in excluded list)
    processable_columns = [col for col in df.columns if col not in excluded_columns]
    
    for column in processable_columns:
        # Safely apply the transformation
        try:
            # Check if the column has any non-null values before processing
            if df[column].notna().any():
                if column in account_number_columns:
                    # Special handling for account numbers - keep '/' and '-'
                    df[column] = df[column].apply(
                        lambda x: re.sub(r'[^a-zA-Z0-9/\-]', '', str(x)) if pd.notnull(x) else x
                    )
                elif column in address_columns:
                    # Keep '&' in address columns
                    df[column] = df[column].apply(
                        lambda x: re.sub(r'[^a-zA-Z0-9&]', ' ', str(x)) if pd.notnull(x) else x
                    )
                    # df[column] = df[column].apply(lambda x: x.replace('&', 'and') if isinstance(x, str)else x)
                else:
                    df[column] = df[column].apply(
                        lambda x: re.sub(r'[^a-zA-Z0-9]', ' ', str(x)) if pd.notnull(x) else x
                    )
                # Remove double spaces
                df[column] = df[column].apply(lambda x: re.sub(r'\s+', ' ', x).strip() if isinstance(x, str) else x)
        except Exception as e:
            print(f"Error processing column {column}: {e}")

    # Now handle specific columns to remove spaces
    # ------------------------------------------------# take notr of this.-------------------------------------------------------
    for col in ['CUSTOMERID', 'TAXID', 'OTHERID','LEGALCHALLENGESTATUS','LOANSECURITYSTATUS','ACCOUNTSTATUS']:
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
                df[col] = df[col].apply(
                    lambda x: x if pd.notnull(x) and (
                        x.endswith('@gmail.com') or 
                        x.endswith('@yahoo.com')) or 
                        # x.endswith('.co.uk')) or 
                        x.endswith('.com') or
                        x.endswith('.ng') or
                        x.endswith('.net') or
                        x.endswith('.org') or
                        x.endswith('.biz') or
                        x.endswith('.info') or
                        # x.endswith('.co.uk') or
                        x.endswith('.us')
                else ''
                )
            except Exception as e:
                print(f"Error processing email column {col}: {e}")
    
    return df

def replace_ampersands(df):
    """
    Replace all instances of '&' with 'And' across all string columns in the DataFrame
    """
    # Remove duplicate columns to avoid DataFrame return from df[column]
    df = df.loc[:, ~df.columns.duplicated()]
    for column in df.columns:
        # Only process object (string) columns
        if df[column].dtype == 'object':
            df[column] = df[column].apply(
                lambda x: str(x).replace('&', 'And') if pd.notna(x) else x
            )
    print("Replaced '&' with 'And' across all string columns")
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
    passport_columns = ['PASSPORTNUMBER',
                        'PRINCIPALOFFICER1PASSPORTNUMBER',
                        'PRINCIPALOFFICER2PASSPORTNUMBER',
                        'GUARNATORINTLPASSPORTNUMBER']  # You can add more columns to this list if needed
    
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
                # Discard if the cleaned ID is not exactly 11 or 10 characters
                if len(passport_str) not in [9,10,11]:
                    return ''
                return passport_str  # Keep alphanumeric values

            # Apply the cleaning function to the PASSPORT_NUMBER column
            df[column_name] = df[column_name].apply(clean_passport)

    return df
def process_identity_numbers(df):
    """
    Cleans the National Identity Number columns based on specified criteria.
    
    Updated Criteria:
    - Each ID must be exactly 10 or 11 characters long. If the cleaned ID is not exactly 10 or 11 characters, it is discarded.
    - The ID must either:
      a) Start with two letters (case insensitive) immediately followed by a digit, OR
      b) Be exactly 11 numeric digits (and not repetitive like 11111111111)
    - If neither pattern is met, the ID is discarded.
    
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
        'GUARANTORNATIONALIDNUMBER',
    ]
    
    for column_name in identity_columns:
        if column_name in df.columns:
            def clean_identity(identity):
                # Convert the value to a string
                identity_str = str(identity)
                # Remove all non-alphanumeric characters (i.e., spaces and special characters)
                identity_str = re.sub(r'[^a-zA-Z0-9]', '', identity_str)
                
                # Case 1: Check for purely numeric IDs that are exactly 11 digits
                if identity_str.isdigit() and len(identity_str) == 11:
                    # Check if it's not a repetitive pattern (all same digit)
                    if len(set(identity_str)) > 1:  # More than one unique digit
                        return identity_str
                    return ''  # Repetitive numeric pattern, discard
                
                # Discard if the cleaned ID is not exactly 10 or 11 characters
                if len(identity_str) not in [10, 11]:
                    return ''
                
                # Check that the ID starts with two letters followed immediately by a digit
                if not re.match(r'^[a-zA-Z]{2}\d', identity_str):
                    return ''
                
                return identity_str
            
            df[column_name] = df[column_name].apply(clean_identity)
    
    return df

def process_tax_numbers(df):

    
    # List of National Identity Number columns to process
    identity_columns = [
            'TAXID'
    ]
    
    for column_name in identity_columns:
        if column_name in df.columns:
            def clean_identity(identity):
                # Convert the value to a string
                identity_str = str(identity)
                # Remove all non-alphanumeric characters (i.e., spaces and special characters)
                identity_str = re.sub(r'[^a-zA-Z0-9]', '', identity_str)
                
                if identity_str.isdigit():
                    # Check if it's not a repetitive pattern (all same digit)
                    if len(set(identity_str)) > 1:  # More than one unique digit
                        return identity_str
                    return ''  # Repetitive numeric pattern, discard
                
                # Discard if the cleaned ID is not exactly 10 or 11 characters
                if len(identity_str) not in [9, 10, 11]:
                    return ''
                
                #  Check that the ID starts with two letters followed immediately by a digit
                # if not re.match(r'^[a-zA-Z]{1}\d', identity_str):
                #     return ''
                
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
            'PRINCIPALOFFICER2DRIVERSLISCENCENUMBER',
            'GUARANTORDRIVERSLICENCENUMBER']  # You can add more columns to this list if needed
    
    for column_name in dLicense:
        if column_name in df.columns:
            def clean_driversLicense(value):
                # Convert the value to a string
                value_str = str(value)
                # Remove all non-alphanumeric characters (i.e., spaces and special characters)
                value_str = re.sub(r'[^a-zA-Z0-9]', '', value_str)
                
                if len(value_str) not in [10, 11, 12]:
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
            
            # Keep only values that start with "RN", "BC", or "BN" (case-insensitive)
            df[col] = df[col].where(
                # df[col].str.contains(r'(?=.*[a-zA-Z])(?=.*\d)', regex=True), 
                df[col].str.match(r'^(rn|bc|bn|rc)', case=False).fillna(False),
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
       'OTHERID',
       'PRINCIPALOFFICER1OTHERID',
       'PRINCIPALOFFICER2OTHERID',
       'GUARANTOROTHERID'
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
    threshold_score = 98

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

def map_poistioninBusiness(value):
    """Maps account status values to standardized format."""
    if pd.isna(value) or value is None:
        return None
    
    # Convert to string and clean
    value = str(value).lower()
    value = re.sub(r'[^a-zA-Z0-9]', '', value)
    
    for category, values in Positioninbusiness_dict.items():
        # Convert dictionary values to lowercase and remove special characters for comparison
        dict_values = [str(v).lower().replace(r'[^a-zA-Z0-9]', '') for v in values]
        if value in dict_values:
            return category
    return None  # Return None if no match is found

def positioninBusiness(df):
    """Process account status fields in the DataFrame."""
    # Define the account status columns to look for
    status_columns = [
        'PRINCIPALOFFICER1POSITIONINBUSINESS',
        'PRINCIPALOFFICER2POSITIONINBUSINESS', 

    ]

    # Iterate through the list of potential account status columns
    for col in status_columns:
        if col in df.columns:
            print(f"Processing account status column: {col}")
            
            # Clean the account status values
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)
            df[col] = df[col].apply(lambda x: re.sub(r'[^a-zA-Z0-9]', '', x) if isinstance(x, str) else x)
            df[col] = df[col].apply(map_poistioninBusiness)
            
            # Print unique values after processing
            print(f"Unique values in {col} after processing:", df[col].unique())
    
    return df

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
def map_accountStatus(value):
    """Maps account status values to standardized format."""
    if pd.isna(value) or value is None:
        return None
    
    # Convert to string and clean
    value = str(value).lower()
    value = re.sub(r'[^a-zA-Z0-9]', '', value)
    
    for category, values in AccountStatus_dict.items():
        # Convert dictionary values to lowercase and remove special characters for comparison
        dict_values = [re.sub(r'[^a-zA-Z0-9]', '', str(v).lower()) for v in values]
        if value in dict_values:
            return category
    return None  # Return None if no match is found

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
    # Clean the input
    loan_name_clean = re.sub(r'[^a-zA-Z0-9]', '', str(loan_name)).lower()
    # Clean and compare each dictionary value
    for loan_code, names in Loan_dict.items():
        for name in names:
            name_clean = re.sub(r'[^a-zA-Z0-9]', '', str(name)).lower()
            if loan_name_clean == name_clean:
                return loan_code
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
                    
                    # First extract only digits from the string, keeping spaces to separate numbers
                    df[col] = df[col].apply(lambda x: ''.join(char if char.isdigit() or char in [',', ';', '/', '|', '-', ' '] else ' ' for char in str(x)))
                    
                    # Split on any non-digit character and take the first non-empty number
                    df[col] = df[col].apply(lambda x: next((num.strip() for num in re.split(r'\D+', x) if num.strip()), ''))
                    
                     # Pad with zeros if less than 11 digits
                    # df[col] = df[col].apply(lambda x: x.zfill(11) if x and len(x) < 11 else x)
                    # Pad with zeros at the BEGINNING if less than 11 digits
                    df[col] = df[col].apply(lambda x: x.rjust(11, '0') if x and len(x) < 11 else x)
                    
                    # New validation: Check if number > 11 digits and doesn't start with 234
                    df[col] = df[col].apply(lambda x: '' if len(x) > 11 and not x.startswith('234') else x)

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
            'dys':1,
            'week': 7,
            'weeks': 7,
            'w': 7,
            'month': 30,
            'mnth':30,
            'mth':30,
            'mths':30,
            'mnths':30,
            'mons':30,
            'months': 30,
            'm': 30,
            'year': 365,
            'years': 365,
            'y': 365,
            'yr': 365,
            'yrs': 365,
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
            numeric_series = pd.to_numeric(df[col], errors='coerce').fillna(0)
            df[col] = np.ceil(numeric_series).astype(int)
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
    x = re.sub(r'[-?]', '', x)  # Remove specific special characters
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

def process_collateral_details(df):
    """
    Process the COLLATERALDETAILS column by removing numeric values and special characters.
    Preserves spaces between words for readability.
    
    Args:
        df (pd.DataFrame): Input DataFrame containing COLLATERALDETAILS column
        
    Returns:
        pd.DataFrame: DataFrame with cleaned COLLATERALDETAILS column
    """
    if 'COLLATERALDETAILS' in df.columns:
        def clean_collateral_details(text):
            if pd.isna(text) or not isinstance(text, str):
                return text
            
            # Remove numeric values
            text = re.sub(r'\d+', '', text)
            
            # Remove special characters but preserve spaces and ampersands
            # text = re.sub(r'[^a-zA-Z\s&]', '', text)
            
            # # Remove multiple spaces and strip
            # text = re.sub(r'\s+', ' ', text).strip()
            
            return text
            
        df['COLLATERALDETAILS'] = df['COLLATERALDETAILS'].apply(clean_collateral_details)
    
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
  

#   --------------------------------------------------TEST THIS MERGE IF ITS OKAY____-----------------------------------------------------
    # Merge with guarantor information
    merge_attempted = False
    try:
        print("Attempting primary merge with ACCOUNTNUMBER")
        temp_merge = pd.merge(
            indi,
            guar,
            left_on='ACCOUNTNUMBER',
            right_on='CUSTOMERSACCOUNTNUMBER',
            how='left',
            indicator=True
        )
        merge_attempted = True
        print(f"Guarantor merge on ACCOUNTNUMBER shape: {temp_merge.shape}")
        print("Merge indicator counts:")
        print(temp_merge['_merge'].value_counts())
        
        # Check if we need fallback merge
        if temp_merge['_merge'].eq('left_only').all():
            print("No matches found in primary merge, attempting fallback merge with credit CUSTOMERID")
            # First merge guarantor with credit on CUSTOMERID
            guar_credit_merge = pd.merge(
                guar,
                credit[['CUSTOMERID', 'ACCOUNTNUMBER']],  # Only take necessary columns from credit
                left_on='CUSTOMERSACCOUNTNUMBER',
                right_on='CUSTOMERID',
                how='inner'  # Only keep matches between guarantor and credit
            )
            
            if not guar_credit_merge.empty:
                # Then merge this result with indi
                fallback_merge = pd.merge(
                    indi,
                    guar_credit_merge,
                    on='ACCOUNTNUMBER',
                    how='left',
                    indicator=True
                )
                print("Fallback merge analysis:")
                print(fallback_merge['_merge'].value_counts())
                # Drop the extra CUSTOMERID column from credit if it exists
                columns_to_drop = ['_merge', 'CUSTOMERID_y'] if 'CUSTOMERID_y' in fallback_merge.columns else ['_merge']
                indi = fallback_merge.drop(columns=columns_to_drop)
                if 'CUSTOMERID_x' in indi.columns:
                    indi = indi.rename(columns={'CUSTOMERID_x': 'CUSTOMERID'})
                print(f"Fallback guarantor merge completed. Final shape: {indi.shape}")
            else:
                print("No matches found in fallback merge")
                indi = temp_merge.drop(columns=['_merge'])
        else:
            indi = temp_merge.drop(columns=['_merge'])
            print(f"Primary guarantor merge successful. Final shape: {indi.shape}")
            
    except Exception as e:
        print(f"Guarantor merge failed: {str(e)}")
        print("Continuing with original data")
        if '_merge' in indi.columns:
            indi = indi.drop(columns=['_merge'])
    indi.drop(columns=['NUMBEROFDIRECTORS'], inplace=True)
   
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
            
            # Store the original combined name for potential reverting
            original_combined_name = f"{row['SURNAME']} {row['FIRSTNAME']} {row['MIDDLENAME']}".strip()
            commercial_row['ORIGINAL_BUSINESSNAME'] = original_combined_name
            
            # Combine names into SURNAME, drop other name columns
            commercial_row['SURNAME'] = original_combined_name
            # commercial_row = commercial_row.drop(['FIRSTNAME', 'MIDDLENAME'])
            # Set DATA column to 'D'
            commercial_row['DATA'] = 'D'
            # Append to commercial entities
            corpo2 = pd.concat([corpo2, pd.DataFrame([commercial_row])], ignore_index=True)
            rows_to_remove.append(index)
    
    # Remove identified commercial entities from individual borrowers
    indi = indi.drop(rows_to_remove).reset_index(drop=True)
    
    # After creation, ensure DATA column exists and is filled, and replace None with ''
    if not corpo2.empty:
        if 'DATA' not in corpo2.columns:
            corpo2['DATA'] = 'D'
        corpo2['DATA'] = corpo2['DATA'].fillna('D')
        corpo2 = corpo2.where(pd.notnull(corpo2), '')
    
    return indi, corpo2

def is_consumer_entity(name, commercial_keywords, threshold=90):
    """
    Check if a business name is likely a consumer entity by confirming it doesn't contain (fuzzy) commercial keywords as standalone words.
    Uses fuzzy matching for standalone words only.
    """
    if name is None or not isinstance(name, str) or not name.strip():
        return False
    
    # Convert to lowercase and split into words for single word matching
    name_words = set(name.lower().split())
    commercial_keywords_lower = [keyword.lower() for keyword in commercial_keywords]
    
    # Fuzzy match: only match if a word in the business name is a fuzzy match to a commercial keyword
    for word in name_words:
        for keyword in commercial_keywords_lower:
            if fuzz.ratio(word, keyword) >= threshold:
                # If the word is a fuzzy match to a commercial keyword, it's not a consumer entity
                return False
    return True

def split_consumer_entities(corpo):
    """
    FIXED: This function now correctly splits a business name into a maximum
    of three parts and preserves the original business name for reverting.
    """
    if 'BUSINESSNAME' not in corpo.columns:
        return corpo, pd.DataFrame()
        
    indi2 = pd.DataFrame()
    rows_to_remove = []
    
    for index, row in corpo.iterrows():
        if pd.isna(row['BUSINESSNAME']):
            continue
        
        business_name = str(row['BUSINESSNAME']).strip()
        
        if is_consumer_entity(business_name, commercial_keywords):
            consumer_data = row.to_dict()
            
            # Store the original name for records that might be sent back
            consumer_data['ORIGINAL_BUSINESSNAME'] = business_name
            
            # Split the business name into a max of 3 parts
            name_parts = business_name.split(maxsplit=2)
            
            # Assign name parts correctly
            consumer_data['SURNAME'] = name_parts[0] if len(name_parts) > 0 else ''
            consumer_data['FIRSTNAME'] = name_parts[1] if len(name_parts) > 1 else ''
            consumer_data['MIDDLENAME'] = name_parts[2] if len(name_parts) > 2 else ''
            consumer_data['DEPENDANTS'] = '00'
            consumer_data['DATA'] = 'D'

            # Remove the original BUSINESSNAME key to avoid conflicts
            if 'BUSINESSNAME' in consumer_data:
                del consumer_data['BUSINESSNAME']

            temp_df = pd.DataFrame([consumer_data])
            indi2 = pd.concat([indi2, temp_df], ignore_index=True)
            rows_to_remove.append(index)
            
    if not corpo.empty and rows_to_remove:
        corpo = corpo.drop(rows_to_remove).reset_index(drop=True)
    
    if not indi2.empty:
        indi2 = indi2.where(pd.notnull(indi2), '')

    return corpo, indi2

def merge_dataframes(processed_sheets):
    """
    Main merging function with sequential processing
    
    Args:
        processed_sheets (dict): Dictionary of processed DataFrames
    
    Returns:
        tuple: (Individual borrowers DataFrame, Corporate borrowers DataFrame)
    """
    # Check if we have merged sheets
    if 'consumermerged' in processed_sheets or 'commercialmerged' in processed_sheets:
        print("\n=== PROCESSING MERGED SHEETS ===")
        indi = processed_sheets.get('consumermerged', pd.DataFrame())
        corpo = processed_sheets.get('commercialmerged', pd.DataFrame())
    else:
        indi = processed_sheets.get('individualborrowertemplate', pd.DataFrame())
        corpo = processed_sheets.get('corporateborrowertemplate', pd.DataFrame())
        
        # Apply null value cleaning
        indi = indi.applymap(lambda x: None if str(x).strip().lower() in ['none', 'nan', 'null', 'nill', 'nil'] else x)
        corpo = corpo.applymap(lambda x: None if str(x).strip().lower() in ['none', 'nan', 'null', 'nill', 'nil'] else x)
        
        print("\n=== MERGED SHEET DATA (Before Split) ===")
        print("Individual records:", len(indi))
        print("Corporate records:", len(corpo))

        # --- Added Processing for Merged Sheets ---
        # Split commercial entities from the consumer_merged data
        if not indi.empty:
            print("\nSplitting commercial entities from consumer_merged data...")
            indi, corpo2 = split_commercial_entities(indi)
            print(f"  - Individual records after split: {len(indi)}")
            print(f"  - Commercial entities extracted: {len(corpo2)}")

            # Rename and concatenate if commercial entities were found
            if not corpo2.empty:
                print("\nRenaming columns for extracted commercial entities...")
                corpo2 = rename_columns(corpo2, ConsuToComm.copy())
                
                # Ensure both dataframes have reset indexes
                if not corpo.empty:
                    corpo = corpo.reset_index(drop=True)
                corpo2 = corpo2.reset_index(drop=True)
                
                print("\nConcatenating extracted commercial entities with corporate data...")
                try:
                    # If corpo is empty, just use corpo2
                    if corpo.empty:
                        corpo = corpo2
                        print(f"  - Using extracted commercial entities as corporate data: {len(corpo)} rows")
                    else:
                        # Use columns parameter to ensure concatenation uses only columns from mapping
                        common_columns = [col for col in corpo2.columns if col in corpo.columns]
                        if not common_columns:
                            # If no common columns, use all columns from corpo2
                            corpo = pd.concat([corpo, corpo2], ignore_index=True, sort=False)
                        else:
                            corpo = pd.concat([corpo[common_columns], corpo2[common_columns]], ignore_index=True)
                        print(f"  - Total corporate records after concatenation: {len(corpo)}")
                except Exception as e:
                    print(f"Error during commercial concatenation: {e}")
                    print(f"corpo columns: {list(corpo.columns)}")
                    print(f"corpo2 columns: {list(corpo2.columns)}")
                    # If concatenation fails, at least ensure corpo2 is preserved
                    if corpo.empty:
                        corpo = corpo2.copy()
                        print("Using only extracted commercial entities as corporate data")
        
        # Split consumer entities from the commercial_merged data
        if not corpo.empty:
            print("\nSplitting consumer entities from commercial_merged data...")
            corpo, indi2 = split_consumer_entities(corpo)
            print(f"  - Corporate records after split: {len(corpo)}")
            print(f"  - Consumer entities extracted: {len(indi2)}")

            # Rename and concatenate if consumer entities were found
            if not indi2.empty:
                print("\nRenaming columns for extracted consumer entities...")
                # Apply the CommToConsu mapping to rename columns and strictly order them
                indi2 = rename_columns(indi2, CommToConsu.copy())
                
                # Ensure both dataframes have reset indexes
                indi = indi.reset_index(drop=True)
                indi2 = indi2.reset_index(drop=True)
                
                print("\nConcatenating extracted consumer entities with individual data...")
                try:
                    # If indi is empty, just use indi2
                    if indi.empty:
                        indi = indi2
                        print(f"  - Using extracted consumer entities as individual data: {len(indi)} rows")
                    else:
                        # Ensure both dataframes have the same column ordering by applying the same mapping
                        indi = rename_columns(indi, CommToConsu.copy())
                        indi2 = rename_columns(indi2, CommToConsu.copy())
                        
                        # Direct concatenation without filtering to common columns
                        indi = pd.concat([indi, indi2], ignore_index=True, sort=False)
                        print(f"Total individual borrowers after concatenation: {len(indi)}")
                except Exception as e:
                    print(f"Error during consumer concatenation: {str(e)}")
                    print(f"indi columns: {list(indi.columns)}")
                    print(f"indi2 columns: {list(indi2.columns)}")
                    # If concatenation fails, at least ensure indi2 is preserved
                    if indi.empty:
                        indi = indi2.copy()
                        print("Using only extracted consumer entities as individual data")
        # --- End Added Processing ---
                
        print("\n=== FINAL MERGED SHEET DATA ===")
        print("Final Individual records:", len(indi))
        print("Final Corporate records:", len(corpo))
        
        return indi, corpo

    # Regular processing for non-merged sheets
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
    print(corpo.head())
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
        
        # Ensure both dataframes have reset indexes
        corpo = corpo.reset_index(drop=True)
        corpo2 = corpo2.reset_index(drop=True)
        
        # Combine commercial entities with existing corporate borrowers
        try:
            # If corpo is empty, just use corpo2
            if corpo.empty:
                corpo = corpo2
                print(f"Using extracted commercial entities as corporate data: {len(corpo)} rows")
            else:
                # Apply ConsuToComm mapping to ensure columns are aligned
                corpo2 = rename_columns(corpo2, ConsuToComm.copy())
                
                # Direct concatenation without filtering to common columns
                corpo = pd.concat([corpo, corpo2], ignore_index=True, sort=False)
                print(f"Total corporate borrowers after concatenation: {len(corpo)}")
        except Exception as e:
            print(f"Error during commercial concatenation: {e}")
            print(f"corpo columns: {list(corpo.columns)}")
            print(f"corpo2 columns: {list(corpo2.columns)}")
            # If concatenation fails, at least ensure corpo2 is preserved
            if corpo.empty:
                corpo = corpo2.copy()
                print("Using only extracted commercial entities as corporate data")

        # Additional check to verify commercial entities were added
        commercial_entities_in_corpo = pd.DataFrame()
        if 'BUSINESSNAME' in corpo.columns:
            commercial_entities_in_corpo = corpo[
                corpo['BUSINESSNAME'].apply(
                    lambda x: any(keyword in str(x).lower() for keyword in commercial_keywords)
                )
            ]
            print("\nCommercial Entities in Final Corporate Borrowers:")
            print("Number of commercial entities:", len(commercial_entities_in_corpo))
            print("First few commercial entities:")
            print(commercial_entities_in_corpo.head())
        else:
            print("\nWARNING: 'BUSINESSNAME' column not found in corporate DataFrame")
            print("Cannot identify commercial entities in corporate borrowers")
    
    # Step 5: Split consumer entities from corporate borrowers
    corpo, indi2 = split_consumer_entities(corpo)
    
    print("\n=== SPLIT CONSUMER ENTITIES ===")
    print("Corporate records after split:", len(corpo))
    print("Consumer entities extracted:", len(indi2))
    
    # Step 6: Rename consumer entities before combining
    if not indi2.empty:
        # Rename indi2 columns to match individual borrower template
        print("\nRenaming columns for extracted consumer entities...")
        indi2 = rename_columns(indi2, CommToConsu.copy())
        
        # Debug statement to show indi2 details before concatenation
        print("Number of consumer entities:", len(indi2))
        print("First few rows of indi2:")
        print(indi2.head())
        
        # Ensure both dataframes have reset indexes
        indi = indi.reset_index(drop=True)
        indi2 = indi2.reset_index(drop=True)
        
        # Combine consumer entities with existing individual borrowers
        try:
            # If indi is empty, just use indi2
            if indi.empty:
                indi = indi2
                print(f"Using extracted consumer entities as individual data: {len(indi)} rows")
            else:
                # Ensure indi has the same column ordering as CommToConsu
                indi = rename_columns(indi, CommToConsu.copy())
                
                # Now both dataframes have exactly the same columns in the same order,
                # we can safely concatenate them
                indi = pd.concat([indi, indi2], ignore_index=True)
                print(f"Total individual records after concatenation: {len(indi)}")
                    
            # Debug statement to confirm addition
            print("\nAfter Adding Consumer Entities:")
            print("Total individual borrowers:", len(indi))
            print("Columns in final indi:", list(indi.columns[:10]) + ["..."])  # Show first 10 columns
            print("First few rows after addition:")
            print(indi.head())
        except Exception as e:
            print(f"Error during consumer concatenation: {str(e)}")
            print(f"indi columns: {list(indi.columns)}")
            print(f"indi2 columns: {list(indi2.columns)}")
            # If concatenation fails, at least ensure indi2 is preserved
            if indi.empty:
                indi = indi2.copy()
                print("Using only extracted consumer entities as individual data")
    
    return indi, corpo
 
def rename_columns(df, column_mapping):
    """
    Rename columns based on a mapping dictionary and strictly enforce column order
    
    Args:
        df (pd.DataFrame): Input DataFrame
        column_mapping (dict): Mapping of column names
    
    Returns:
        pd.DataFrame: DataFrame with renamed columns and ordered according to mapping
    """
    try:
        # Create a fresh copy of the dataframe to avoid modifying the original
        df = df.copy()
        
        # Print original columns before renaming
        print("Original columns before renaming:", list(df.columns))
        print("Mapping dictionary has", len(column_mapping), "keys")

        # Rename columns that match the mapping
        for column in list(df.columns):  # Use list() to create a copy of columns
            for mapped_column, alt_names in column_mapping.items():
                if column in alt_names or column.lower() in alt_names or column.upper() in alt_names:
                    df.rename(columns={column: mapped_column}, inplace=True)
                    print(f"Renamed {column} to {mapped_column}")
                    break
        
        # Print columns after initial renaming
        print("Columns after renaming:", list(df.columns))

        # Check for duplicate columns and make them unique
        if len(df.columns) != len(set(df.columns)):
            print("WARNING: Duplicate column names detected, making them unique...")
            # Create a new columns list without duplicates
            seen = set()
            new_columns = []
            for col in df.columns:
                if col not in seen:
                    seen.add(col)
                    new_columns.append(col)
                else:
                    # For duplicates, add a suffix
                    i = 1
                    while f"{col}_{i}" in seen:
                        i += 1
                    seen.add(f"{col}_{i}")
                    new_columns.append(f"{col}_{i}")
            
            # Assign the new unique column names
            df.columns = new_columns
        
        # Print columns before final reordering
        print("Columns before reordering:", list(df.columns))

        # Create ordered DataFrame using concat instead of adding columns one by one
        # This avoids DataFrame fragmentation warning
        column_dfs = []
        for col in column_mapping.keys():
            if col in df.columns:
                # For existing columns, use the values from the original DataFrame
                column_dfs.append(pd.DataFrame({col: df[col]}))
            else:
                # For missing columns, create a new DataFrame with None values
                column_dfs.append(pd.DataFrame({col: [None] * len(df)}))
        
        # Use concat to join all columns at once
        if column_dfs:
            ordered_df = pd.concat(column_dfs, axis=1)
        else:
            # If no columns were found, create an empty DataFrame with the right columns
            ordered_df = pd.DataFrame(columns=list(column_mapping.keys()))
        
        # Reset index to ensure clean index for concatenation
        ordered_df = ordered_df.reset_index(drop=True)
        
        # Print final columns
        print("Final columns after strict reordering:", list(ordered_df.columns))
        print(f"Final dataframe has {len(ordered_df.columns)} columns and {len(ordered_df)} rows")

        return ordered_df
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

def convert_numpy(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

from django.contrib.auth.decorators import login_required

@login_required
def upload_file(request):
    if request.method == 'POST':
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']
            original_filename = os.path.splitext(uploaded_file.name)[0]
            
            # Extract subscriber alias from filename by removing date patterns
            subscriber_alias = extract_subscriber_alias_from_filename(original_filename)
            
            fs = FileSystemStorage()
            filename = fs.save(uploaded_file.name, uploaded_file)
            file_path = os.path.join(settings.MEDIA_ROOT, filename)
            try:
                xds = pd.read_excel(file_path, sheet_name=None, na_filter=False, dtype=object)
                processing_stats = []
                for sheet_name, df in xds.items():
                    initial_records = len(df)
                    processing_stats.append({
                        'sheet_name': sheet_name,
                        'initial_columns': len(df.columns),
                        'initial_records': initial_records,
                        'processed_columns': None,
                        'valid_records': 0
                    })
                    for col in df.columns:
                        df[col] = df[col].astype(str)
                        df[col] = df[col].replace({'nan': '', 'None': '', 'NaN': ''})
                    xds[sheet_name] = df
                processed_sheets = ensure_all_sheets_exist(xds)
                for sheet_name, sheet_data in xds.items():
                    print(f"\n[DEBUG] Original headers in uploaded file for sheet '{sheet_name}': {list(sheet_data.columns)}")
                    cleaned_name = clean_sheet_name(sheet_name)
                    cleaned_df = sheet_data.copy()
                    cleaned_df.replace(['N/A', 'N.A', 'None', "NaN", "null", "n/a", "#N/A",'NIL','Nill','NA'], '', inplace=True)
                    print(f"[DEBUG] Headers after pandas loads the file: {list(cleaned_df.columns)}")
                    cleaned_df.columns = [str(col).upper().strip() for col in cleaned_df.columns]
                    cleaned_df = preprocess_tenor_from_headers(cleaned_df)
                    cleaned_df.columns = [remove_special_characters(col) for col in cleaned_df.columns]
                    print(f"[DEBUG] Headers after cleaning: {list(cleaned_df.columns)}")
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
                    elif cleaned_name == 'consumermerged':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, consumer_merged_mapping)
                    elif cleaned_name == 'commercialmerged':
                        cleaned_df = rename_columns_with_fuzzy_rapidfuzz(cleaned_df, commercial_merged_mapping)
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
                    cleaned_df = process_dates(cleaned_df)
                    cleaned_df = process_names(cleaned_df)
                    cleaned_df = process_special_characters(cleaned_df)
                    cleaned_df = replace_ampersands(cleaned_df)
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
                    cleaned_df = process_tax_numbers(cleaned_df)
                    cleaned_df = process_collateral_details(cleaned_df)
                    cleaned_df = positioninBusiness(cleaned_df)
                    cleaned_df = trim_strings_to_59(cleaned_df)

                    for stat in processing_stats:
                        if stat['sheet_name'] == sheet_name:
                            stat['processed_columns'] = len(cleaned_df.columns)
                            break
                    processed_sheets[cleaned_name] = cleaned_df

                # --- Human-in-the-loop: Extract split candidates ---
                # Use the same logic as merge_dataframes, but pause after split candidates are identified
                # FIX: Use merged sheets directly if present
                if 'consumermerged' in processed_sheets or 'commercialmerged' in processed_sheets:
                    indi = processed_sheets.get('consumermerged', pd.DataFrame())
                    corpo = processed_sheets.get('commercialmerged', pd.DataFrame())
                else:
                    consu = processed_sheets.get('individualborrowertemplate', pd.DataFrame())
                    comm = processed_sheets.get('corporateborrowertemplate', pd.DataFrame())
                    credit = processed_sheets.get('creditinformation', pd.DataFrame())
                    guar = processed_sheets.get('guarantorsinformation', pd.DataFrame())
                    prin = processed_sheets.get('principalofficerstemplate', pd.DataFrame())
                    indi = merge_individual_borrowers(consu, credit, guar)
                    corpo = merge_corporate_borrowers(comm, credit, prin)

                # Split commercial entities from individual borrowers (candidates for manual review)
                split_indi, split_candidates_commercial = split_commercial_entities(indi)
                # Split consumer entities from corporate borrowers (candidates for manual review)
                split_corpo, split_candidates_consumer = split_consumer_entities(corpo)
                # Store all data in session for next step
                request.session['split_candidates_commercial'] = split_candidates_commercial.to_json(orient='split')
                request.session['split_candidates_consumer'] = split_candidates_consumer.to_json(orient='split')
                request.session['indi'] = split_indi.to_json(orient='split')
                request.session['corpo'] = split_corpo.to_json(orient='split')
                request.session['processing_stats'] = json.loads(json.dumps(processing_stats, default=convert_numpy))
                request.session['original_filename'] = original_filename
                request.session['subscriber_alias'] = subscriber_alias
                # Reorder columns for consumer candidates
                reordered_consumer_columns = reorder_consumer_columns(split_candidates_consumer.columns)
                
                # Reindex the DataFrame with the new column order
                split_candidates_consumer = split_candidates_consumer.reindex(columns=reordered_consumer_columns)
                
                # Render verification page with all split candidates
                commercial_records = json.loads(split_candidates_commercial.to_json(orient='records'))
                consumer_records = json.loads(split_candidates_consumer.to_json(orient='records'))
                return render(request, 'verify_split.html', {
                    'form': form,
                    'commercial_candidates': commercial_records,
                    'consumer_candidates': consumer_records,
                    'columns_commercial': list(split_candidates_commercial.columns),
                    'columns_consumer': reordered_consumer_columns,  # Use the reordered columns
                    'processing_stats': processing_stats,
                })
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                return render(request, 'upload.html', {
                    'form': form,
                    'error_message': f'Error Details:\n{error_details}'
                })
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)
    else:
        form = ExcelUploadForm()
    return render(request, 'upload.html', {'form': form})

def clean_for_output(df):
    # Convert all columns to string
    for col in df.columns:
        df[col] = df[col].astype(str)
    # Replace all null/nan/nil/none with empty string
    df.replace(['N/A', 'N.A', 'None', 'NaN', 'nan', 'null', 'n/a', '#N/A', 'NIL', 'Nill', 'nil', 'none', 'None'], '', inplace=True)
    return df

def enforce_string_columns(df):
    for col in df.columns:
        df[col] = df[col].astype(str)
    return df

def reorder_consumer_columns(columns):
    """
    Reorder columns to place SURNAME, FIRSTNAME, MIDDLENAME, and DEPENDANTS 
    immediately after BUSINESSREGISTRATIONNUMBER for better logical grouping.
    
    Args:
        columns (list): List of column names
        
    Returns:
        list: Reordered list of column names
    """
    # Convert to list if it's a pandas Index
    columns = list(columns)
    
    # Define the columns we want to move
    columns_to_move = ['SURNAME', 'FIRSTNAME', 'MIDDLENAME', 'DEPENDANTS']
    
    # Only proceed if all columns to move exist in the DataFrame
    if all(col in columns for col in columns_to_move):
        # Remove the columns we want to move from their current positions
        remaining_columns = [col for col in columns if col not in columns_to_move]
        
        # Find the index of BUSINESSREGISTRATIONNUMBER
        if 'BUSINESSREGISTRATIONNUMBER' in remaining_columns:
            insert_index = remaining_columns.index('BUSINESSREGISTRATIONNUMBER') + 1
            
            # Insert the columns after BUSINESSREGISTRATIONNUMBER
            remaining_columns[insert_index:insert_index] = columns_to_move
            return remaining_columns
    
    # Return original order if we couldn't reorder
    return columns

@csrf_exempt  # You may want to use proper CSRF handling in production
def transform_to_commercial(df):
    """
    Transform individual records to commercial format.
    Only processes checked records that need to be moved to corporate.
    """
    if df.empty:
        return df
    
    df_copy = df.copy()
    
    # Use ORIGINAL_BUSINESSNAME if available, otherwise reconstruct from components
    if 'BUSINESSNAME' not in df_copy.columns:
        if 'ORIGINAL_BUSINESSNAME' in df_copy.columns:
            # Use the stored original business name to prevent duplication
            df_copy['BUSINESSNAME'] = df_copy['ORIGINAL_BUSINESSNAME']
        else:
            # Fallback: reconstruct from individual components if no original name exists
            df_copy['BUSINESSNAME'] = (
                df_copy['SURNAME'].fillna('') + ' '
                + df_copy['FIRSTNAME'].fillna('') + ' '
                + df_copy['MIDDLENAME'].fillna('')
            ).str.strip()
    
    # Drop individual name, dependant, and temporary columns for corporate format
    columns_to_remove = ['SURNAME', 'FIRSTNAME', 'MIDDLENAME', 'DEPENDANTS', 'ORIGINAL_BUSINESSNAME']
    df_copy = df_copy.drop(columns=[col for col in columns_to_remove if col in df_copy.columns], errors='ignore')
    
    # Apply column mapping from consumer to commercial
    df_copy = rename_columns(df_copy, ConsuToComm.copy())
    df_copy = enforce_string_columns(df_copy)
    
    return df_copy


def transform_to_consumer(df):
    """
    Transform commercial records to consumer format.
    Only processes checked records that need to be moved to individual.
    """
    if df.empty:
        return df
    
    df_copy = df.copy()
    
    # Apply column mapping from commercial to consumer
    df_copy = rename_columns(df_copy, CommToConsu.copy())
    df_copy = enforce_string_columns(df_copy)
    
    return df_copy



@login_required
def verify_split_decision(request):
    if request.method == 'POST':
        # Validate required session keys exist
        required_session_keys = ['split_candidates_commercial', 'split_candidates_consumer', 'indi', 'corpo']
        missing_keys = [key for key in required_session_keys if key not in request.session]
        
        if missing_keys:
            messages.error(request, f'Session data missing: {missing_keys}. Please restart the process.')
            return redirect('upload_file')
        
        # Get user checkbox moves from POST (lists of booleans)
        commercial_moves = json.loads(request.POST.get('commercial_moves', '[]'))
        consumer_moves = json.loads(request.POST.get('consumer_moves', '[]'))
        
        # Retrieve stored data from session
        split_candidates_commercial = pd.read_json(request.session['split_candidates_commercial'], orient='split', dtype=str)
        split_candidates_commercial = enforce_string_columns(split_candidates_commercial)
        split_candidates_consumer = pd.read_json(request.session['split_candidates_consumer'], orient='split', dtype=str)
        split_candidates_consumer = enforce_string_columns(split_candidates_consumer)
        indi = pd.read_json(request.session['indi'], orient='split', dtype=str)
        indi = enforce_string_columns(indi)
        corpo = pd.read_json(request.session['corpo'], orient='split', dtype=str)
        corpo = enforce_string_columns(corpo)
        processing_stats = request.session.get('processing_stats', [])
        original_filename = request.session.get('original_filename', 'output')
        subscriber_alias = request.session.get('subscriber_alias', original_filename)
        
        # Extract date from filename for standardized naming
        extracted_month, extracted_year = extract_date_from_filename(original_filename)

        # For commercial candidates: checked = move to corpo, unchecked = stay in indi
        move_to_corp_idx = [i for i, move in enumerate(commercial_moves) if move]
        stay_in_indi_idx = [i for i, move in enumerate(commercial_moves) if not move]

        # Separate checked vs unchecked commercial candidates
        checked_commercial = split_candidates_commercial.iloc[move_to_corp_idx].copy() if move_to_corp_idx else pd.DataFrame()
        unchecked_commercial = split_candidates_commercial.iloc[stay_in_indi_idx].copy() if stay_in_indi_idx else pd.DataFrame()

        # For consumer candidates: checked = move to indi, unchecked = stay in corpo
        move_to_indi_idx = [i for i, move in enumerate(consumer_moves) if move]
        stay_in_corp_idx = [i for i, move in enumerate(consumer_moves) if not move]

        # Separate checked vs unchecked consumer candidates
        checked_consumer = split_candidates_consumer.iloc[move_to_indi_idx].copy() if move_to_indi_idx else pd.DataFrame()
        unchecked_consumer = split_candidates_consumer.iloc[stay_in_corp_idx].copy() if stay_in_corp_idx else pd.DataFrame()

        # Return unchecked records to original DataFrames (no processing)
        if not unchecked_commercial.empty:
            # Restore original individual name structure for unchecked commercial candidates
            if 'ORIGINAL_BUSINESSNAME' in unchecked_commercial.columns:
                # Split the original business name back into individual components
                for idx, row in unchecked_commercial.iterrows():
                    if pd.notna(row['ORIGINAL_BUSINESSNAME']):
                        name_parts = str(row['ORIGINAL_BUSINESSNAME']).split(maxsplit=2)
                        unchecked_commercial.at[idx, 'SURNAME'] = name_parts[0] if len(name_parts) > 0 else ''
                        unchecked_commercial.at[idx, 'FIRSTNAME'] = name_parts[1] if len(name_parts) > 1 else ''
                        unchecked_commercial.at[idx, 'MIDDLENAME'] = name_parts[2] if len(name_parts) > 2 else ''
                # Remove the temporary ORIGINAL_BUSINESSNAME column
                unchecked_commercial = unchecked_commercial.drop(columns=['ORIGINAL_BUSINESSNAME'], errors='ignore')
            indi = pd.concat([indi, unchecked_commercial], ignore_index=True)
        
        if not unchecked_consumer.empty:
            # Restore original business name and clean up individual columns for unchecked consumer records
            if 'ORIGINAL_BUSINESSNAME' in unchecked_consumer.columns:
                unchecked_consumer['BUSINESSNAME'] = unchecked_consumer['ORIGINAL_BUSINESSNAME']
                columns_to_drop = ['ORIGINAL_BUSINESSNAME', 'SURNAME', 'FIRSTNAME', 'MIDDLENAME', 'DEPENDANTS']
                unchecked_consumer = unchecked_consumer.drop(columns=[col for col in columns_to_drop if col in unchecked_consumer.columns], errors='ignore')
            corpo = pd.concat([corpo, unchecked_consumer], ignore_index=True)

        # Transform ONLY checked records
        confirmed_commercial = pd.DataFrame()
        confirmed_consumer = pd.DataFrame()
        
        if not checked_commercial.empty:
            # Transform individual records to commercial format
            confirmed_commercial = transform_to_commercial(checked_commercial)
            
        if not checked_consumer.empty:
            # Transform commercial records to consumer format
            confirmed_consumer = transform_to_consumer(checked_consumer)
            
        # Concatenate only the transformed checked records
        if not confirmed_consumer.empty:
            indi = pd.concat([indi, confirmed_consumer], ignore_index=True)
        if not confirmed_commercial.empty:
            corpo = pd.concat([corpo, confirmed_commercial], ignore_index=True)


        # All further processing should NOT change dtypes, but just in case:
        indi = modify_middle_names(indi)
        corpo = modify_middle_names(corpo)


        indi = remove_duplicates(indi)
        corpo = remove_duplicates(corpo)


        indi = clean_for_output(indi)
        corpo = clean_for_output(corpo)
        # Drop name and dependant columns from corpo again to be sure
        columns_to_remove = ['SURNAME', 'FIRSTNAME', 'MIDDLENAME', 'DEPENDANTS']
        corpo = corpo.drop(columns=[col for col in columns_to_remove if col in corpo.columns], errors='ignore')

        total_individual_records = len(indi) if not indi.empty else 0
        total_corporate_records = len(corpo) if not corpo.empty else 0

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Generate standardized filenames using new naming convention
        indi_output_filename = generate_filename(subscriber_alias, 'excel', 'consumer', extracted_month, extracted_year)
        corpo_output_filename = generate_filename(subscriber_alias, 'excel', 'commercial', extracted_month, extracted_year)
        
        # Use fallback naming if subscriber mapping fails
        if not indi_output_filename:
            indi_output_filename = generate_fallback_filename(original_filename, 'excel', 'consumer', timestamp)
        if not corpo_output_filename:
            corpo_output_filename = generate_fallback_filename(original_filename, 'excel', 'commercial', timestamp)
        
        # For full processed file, use original naming for now (can be updated later if needed)
        full_output_filename = f"{original_filename}_processed_{timestamp}.xlsx"
        excel_dir = os.path.join(settings.MEDIA_ROOT, 'excel')
        excel_individual_dir = os.path.join(excel_dir, 'individual')
        excel_corporate_dir = os.path.join(excel_dir, 'corporate')
        excel_full_dir = os.path.join(excel_dir, 'full')
        os.makedirs(excel_individual_dir, exist_ok=True)
        os.makedirs(excel_corporate_dir, exist_ok=True)
        os.makedirs(excel_full_dir, exist_ok=True)

        fs = FileSystemStorage()
        

        indi_excel_path = os.path.join(excel_individual_dir, indi_output_filename)
        indi.to_excel(indi_excel_path, index=False)
        indi_processed_file_url = fs.url(os.path.join('excel', 'individual', indi_output_filename))
        corpo_excel_path = os.path.join(excel_corporate_dir, corpo_output_filename)
        corpo.to_excel(corpo_excel_path, index=False)
        corpo_processed_file_url = fs.url(os.path.join('excel', 'corporate', corpo_output_filename))
        full_excel_path = os.path.join(excel_full_dir, full_output_filename)
        with pd.ExcelWriter(full_excel_path, engine='openpyxl') as writer:
            indi.to_excel(writer, sheet_name='Merged_Individual_Borrowers', index=False)
            corpo.to_excel(writer, sheet_name='Merged_Corporate_Borrowers', index=False)
        full_processed_file_url = fs.url(os.path.join('excel', 'full', full_output_filename))
        # TXT versions - Generate standardized filenames using new naming convention
        indi_txt_filename = generate_filename(subscriber_alias, 'txt', 'consumer', extracted_month, extracted_year)
        corpo_txt_filename = generate_filename(subscriber_alias, 'txt', 'commercial', extracted_month, extracted_year)
        
        # Use fallback naming if subscriber mapping fails
        if not indi_txt_filename:
            indi_txt_filename = generate_fallback_filename(original_filename, 'txt', 'consumer', timestamp)
        if not corpo_txt_filename:
            corpo_txt_filename = generate_fallback_filename(original_filename, 'txt', 'commercial', timestamp)
        
        # For full processed file, use original naming for now (can be updated later if needed)
        full_txt_filename = f"{original_filename}_processed_{timestamp}.txt"
        txt_dir = os.path.join(settings.MEDIA_ROOT, 'txt')
        os.makedirs(txt_dir, exist_ok=True)
        txt_individual_dir = os.path.join(txt_dir, 'individual')
        txt_corporate_dir = os.path.join(txt_dir, 'corporate')
        txt_full_dir = os.path.join(txt_dir, 'full')
        os.makedirs(txt_individual_dir, exist_ok=True)
        os.makedirs(txt_corporate_dir, exist_ok=True)
        os.makedirs(txt_full_dir, exist_ok=True)
        indi_txt_path = os.path.join(txt_individual_dir, indi_txt_filename)
        indi.to_csv(indi_txt_path, sep='\t', index=False, encoding='utf-8')
        corpo_txt_path = os.path.join(txt_corporate_dir, corpo_txt_filename)
        corpo.to_csv(corpo_txt_path, sep='\t', index=False, encoding='utf-8')
        full_txt_path = os.path.join(txt_full_dir, full_txt_filename)
        with open(full_txt_path, 'w', encoding='utf-8') as f:
            indi.to_csv(f, sep='\t', index=False)
            f.write("\n\n")
            corpo.to_csv(f, sep='\t', index=False)
        indi_txt_url = fs.url(os.path.join('txt', 'individual', indi_txt_filename))
        corpo_txt_url = fs.url(os.path.join('txt', 'corporate', corpo_txt_filename))
        full_txt_url = fs.url(os.path.join('txt', 'full', full_txt_filename))
        return render(request, 'upload.html', {
            'form': ExcelUploadForm(),
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
    else:
        return render(request, 'upload.html', {'form': ExcelUploadForm(), 'error_message': 'Invalid request.'})

def clean_and_deduplicate_columns(df):
    """Clean column names and assign suffixes to duplicates after cleaning."""
    cleaned_cols = [remove_special_characters(str(col)).upper().strip() for col in df.columns]
    counts = {}
    new_cols = []
    for col in cleaned_cols:
        if col in counts:
            counts[col] += 1
            new_cols.append(f"{col}{counts[col]}")
        else:
            counts[col] = 0
            new_cols.append(col)
    df.columns = new_cols
    return df

