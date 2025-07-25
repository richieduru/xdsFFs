import os
import gc
import json
import pandas as pd
import numpy as np
import openpyxl
from datetime import datetime
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django_q.tasks import async_task
from .models import FileProcessingTask
from concurrent.futures import ThreadPoolExecutor
import re
from .filename_utils import generate_filename, generate_fallback_filename
from .views import (
    ensure_all_sheets_exist, clean_sheet_name, preprocess_tenor_from_headers,
    remove_special_characters, make_column_names_unique, 
    rename_columns_with_fuzzy_rapidfuzz, process_dates, process_names,
    process_special_characters, replace_ampersands, process_nationality,
    process_gender, process_states, process_marital_status, process_borrower_type,
    process_employment_status, process_phone_columns, process_title,
    process_account_status, process_loan_type, process_currency, process_repayment,
    process_classification, process_collateral_type, process_loan_tenor,
    clear_previous_info_columns, process_numeric_columns, fill_data_column,
    fill_depend_column, process_identity_numbers, process_passport_number,
    process_business_id, process_bvn_number, process_occu, process_DriversLicense,
    process_otherid, process_tax_numbers, process_collateral_details,
    positioninBusiness, trim_strings_to_59, remove_duplicates,
    merge_individual_borrowers, merge_corporate_borrowers,
    split_commercial_entities, split_consumer_entities,
    consu_mapping, comm_mapping, prin_mapping, credit_mapping, guar_mapping,
    consumer_merged_mapping, commercial_merged_mapping,
    clean_for_output, enforce_string_columns, reorder_consumer_columns,
    transform_to_commercial, transform_to_consumer, modify_middle_names,
    remove_titles, extract_date_from_filename, generate_filename,
    generate_fallback_filename, guarantor_columns_to_clear, principal_officer_columns_to_clear
)

# Pre-compiled regex patterns for performance optimization
TITLES = [
    'Miss', 'Mrs', 'Rev', 'Dr', 'Mr', 'MS', 'CAPT','pastor','doctor',
    'COL', 'LADY', 'MAJ', 'PST', 'PROF', 'REV', 'SGT',
    'SIR', 'HE', 'JUDG', 'CHF', 'ALHJ', 'APOS', 'CDR', 'ALH', 'Alh',
    'BISH', 'FLT', 'BARR', 'MGEN', 'GEN', 'HON', 'ENGR', 'LT', 'AND', 'and',
    'PASTOR', 'PAST', 'PST', 'ALHAJI', 'ALH', 'ALH.', 'ALHAJ', 'ALHADJI', 
    'ALHAJJI', 'ALHAJ.', 'ALHADJ', 'ALHADJ.', 'PASTOR.', 'PASTOR', 'PAST.', 
    'PST.', 'REV.', 'REV', 'DR.', 'MR.', 'MRS.', 'MS.'
]
TITLE_PATTERN = re.compile(r'\b(?:' + '|'.join(re.escape(title) for title in TITLES) + r')\b', re.IGNORECASE)

# Special character patterns for different column types
GENERAL_SPECIAL_CHARS = re.compile(r'[^a-zA-Z0-9]')
ADDRESS_SPECIAL_CHARS = re.compile(r'[^a-zA-Z0-9&]')  # Preserve & in addresses
ACCOUNT_SPECIAL_CHARS = re.compile(r'[^a-zA-Z0-9/\-]')  # Preserve / and - in account numbers

# Helper functions for parallel file operations
def write_excel_file(df, filepath):
    """Thread-safe Excel file writing using xlsxwriter engine"""
    try:
        df.to_excel(filepath, index=False, engine='xlsxwriter')
        return f"Excel file written successfully: {filepath}"
    except Exception as e:
        raise Exception(f"Error writing Excel file {filepath}: {str(e)}")

def write_txt_file(df, filepath):
    """Thread-safe TXT file writing using tab separation"""
    try:
        df.to_csv(filepath, sep='\t', index=False)
        return f"TXT file written successfully: {filepath}"
    except Exception as e:
        raise Exception(f"Error writing TXT file {filepath}: {str(e)}")

def remove_titles_vectorized(series):
    """Vectorized title removal using pre-compiled regex"""
    return series.str.replace(TITLE_PATTERN, '', regex=True).str.strip()

def process_large_sheet_chunked(file_path, sheet_name, chunk_size=50000):
    """
    Alternative way to process large sheets that avoids the 'chunksize' error
    by manually reading rows using the openpyxl library.
    """
    processed_chunks = []

    # Open the workbook and select the sheet
    workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet = workbook[sheet_name]

    # Get header row from the first row of the sheet
    header = [cell.value for cell in sheet[1]]

    chunk_data = []
    # Start from row 2 to skip the header
    for row_index, row in enumerate(sheet.iter_rows(min_row=2), start=1):
        row_values = [cell.value for cell in row]
        chunk_data.append(row_values)

        # When the chunk is full, create a DataFrame and process it
        if row_index % chunk_size == 0:
            chunk_df = pd.DataFrame(chunk_data, columns=header)
            processed_chunk = process_single_sheet(chunk_df, sheet_name)
            processed_chunks.append(processed_chunk)

            # Clear the list to save memory before the next chunk
            chunk_data = []
            gc.collect()

    # Process the final, smaller chunk if any rows are left
    if chunk_data:
        chunk_df = pd.DataFrame(chunk_data, columns=header)
        processed_chunk = process_single_sheet(chunk_df, sheet_name)
        processed_chunks.append(processed_chunk)

    # Check if any chunks were processed
    if not processed_chunks:
        return pd.DataFrame(columns=header)

    # Combine all processed chunks into the final result
    final_result = pd.concat(processed_chunks, ignore_index=True)

    return final_result
    
def process_single_sheet(sheet_data, sheet_name):
    """
    Apply all data transformation functions to a single sheet with memory optimization
    """
    cleaned_name = clean_sheet_name(sheet_name)
    cleaned_df = sheet_data.copy()
    
    # Clean null values
    cleaned_df.replace(['N/A', 'N.A', 'None', "NaN", "null", "n/a", "#N/A",'NIL','Nill','NA'], '', inplace=True)
    
    # Process headers
    cleaned_df.columns = [str(col).upper().strip() for col in cleaned_df.columns]
    cleaned_df = preprocess_tenor_from_headers(cleaned_df)
    cleaned_df.columns = [remove_special_characters(col) for col in cleaned_df.columns]
    cleaned_df = make_column_names_unique(cleaned_df)
    cleaned_df.columns = [remove_special_characters(col) for col in cleaned_df.columns]
    
    # Apply fuzzy column mapping based on sheet 
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
    
    # Apply ALL the actual data processing functions from views.py
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
    cleaned_df = remove_duplicates(cleaned_df)
    
    # Explicit garbage collection
    gc.collect()
    
    return cleaned_df

def calculate_progress(phase, relative_progress):
    """
    Calculate absolute progress based on phase and relative progress within that phase.
    
    Phase ranges:
    - data_processing: 0-60%
    - verification: 60-80% 
    - finalization: 80-100%
    """
    phase_ranges = {
        'data_processing': (0, 60),
        'verification': (60, 80),
        'finalization': (80, 100)
    }
    
    if phase not in phase_ranges:
        return relative_progress
    
    start, end = phase_ranges[phase]
    return start + (relative_progress * (end - start) / 100)

def process_excel_file_background(task_id, file_path, subscriber_alias, user_id):
    """
    Background task to process large Excel files with sequential processing and memory optimization
    Uses all the actual processing functions from views.py
    """
    task = FileProcessingTask.objects.get(task_id=task_id)
    
    try:
        task.status = 'processing'
        task.progress = calculate_progress('data_processing', 10)
        task.save()
        
        # Sequential sheet processing for memory optimization
        # Load sheet names only first
        with pd.ExcelFile(file_path) as excel_file:
            sheet_names = excel_file.sheet_names
        
        task.progress = calculate_progress('data_processing', 15)
        task.save()
        
        # Initialize processing stats and processed sheets
        processing_stats = []
        processed_sheets = {}
        
        # Process each sheet individually
        total_sheets = len(sheet_names)
        for i, sheet_name in enumerate(sheet_names):
            # Load single sheet
            sheet_data = pd.read_excel(file_path, sheet_name=sheet_name, na_filter=False, dtype=str, engine='openpyxl')
            
            # Initialize processing stats
            initial_records = int(len(sheet_data))
            processing_stats.append({
                'sheet_name': sheet_name,
                'initial_columns': int(len(sheet_data.columns)),
                'initial_records': initial_records,
                'processed_columns': None,
                'valid_records': 0
            })
            
            # Convert all columns to string and clean
            for col in sheet_data.columns:
                sheet_data[col] = sheet_data[col].astype(str)
                sheet_data[col] = sheet_data[col].replace({'nan': '', 'None': '', 'NaN': ''})
            
            # Check if sheet is large and needs chunking
            if len(sheet_data) > 50000:  # Large sheet threshold
                cleaned_name = clean_sheet_name(sheet_name)
                processed_df = process_large_sheet_chunked(file_path, sheet_name)
            else:
                # Process sheet immediately
                processed_df = process_single_sheet(sheet_data, sheet_name)
                cleaned_name = clean_sheet_name(sheet_name)
            
            # Store processed sheet
            processed_sheets[cleaned_name] = processed_df
            
            # Update processing stats for valid records
            for stat in processing_stats:
                if stat['sheet_name'] == sheet_name:
                    if cleaned_name == 'individualborrowertemplate' and 'CUSTOMERID' in processed_df.columns:
                        stat['valid_records'] = int(processed_df['CUSTOMERID'].astype(str).ne('').sum())
                    elif cleaned_name == 'corporateborrowertemplate' and 'CUSTOMERID' in processed_df.columns:
                        stat['valid_records'] = int(processed_df['CUSTOMERID'].astype(str).ne('').sum())
                    elif cleaned_name == 'creditinformation' and 'CUSTOMERID' in processed_df.columns:
                        stat['valid_records'] = int(processed_df['CUSTOMERID'].astype(str).ne('').sum())
                    elif cleaned_name == 'principalofficerstemplate' and 'CUSTOMERID' in processed_df.columns:
                        stat['valid_records'] = int(processed_df['CUSTOMERID'].astype(str).ne('').sum())
                    elif cleaned_name == 'guarantorsinformation' and 'CUSTOMERSACCOUNTNUMBER' in processed_df.columns:
                        stat['valid_records'] = int(processed_df['CUSTOMERSACCOUNTNUMBER'].astype(str).ne('').sum())
                    stat['processed_columns'] = int(len(processed_df.columns))
                    break
            
            # Explicitly clean up raw sheet data
            del sheet_data
            gc.collect()
            
            # Update progress
            relative_progress = 20 + (i + 1) * 40 // total_sheets
            task.progress = calculate_progress('data_processing', relative_progress)
            task.save()
        
        # Ensure all required sheets exist
        required_sheet_names = [
            'individualborrowertemplate',
            'corporateborrowertemplate', 
            'principalofficerstemplate',
            'creditinformation',
            'guarantorsinformation'
        ]
        
        for sheet_name in required_sheet_names:
            if sheet_name not in processed_sheets:
                processed_sheets[sheet_name] = pd.DataFrame()
        
        task.progress = calculate_progress('data_processing', 65)
        task.save()
        
        # Memory-efficient merging with explicit cleanup
        if 'consumermerged' in processed_sheets or 'commercialmerged' in processed_sheets:
            indi = processed_sheets.pop('consumermerged', pd.DataFrame())
            corpo = processed_sheets.pop('commercialmerged', pd.DataFrame())
        else:
            # Extract data for merging - preserve credit for both individual and corporate merges
            consu = processed_sheets.pop('individualborrowertemplate', pd.DataFrame())
            credit_original = processed_sheets.pop('creditinformation', pd.DataFrame())
            guar = processed_sheets.pop('guarantorsinformation', pd.DataFrame())
            
            # Create a copy of credit for individual borrower merge
            credit_for_individual = credit_original.copy() if not credit_original.empty else pd.DataFrame()
            
            indi = merge_individual_borrowers(consu, credit_for_individual, guar)
            
            # Extract corporate data
            comm = processed_sheets.pop('corporateborrowertemplate', pd.DataFrame())
            prin = processed_sheets.pop('principalofficerstemplate', pd.DataFrame())
            
            # Debug: Check data before corporate merge
            # print(f"\n=== CORPORATE MERGE DEBUG ===")
            # print(f"Corporate borrowers shape: {comm.shape}")
            # print(f"Credit original shape: {credit_original.shape}")
            # print(f"Principal officers shape: {prin.shape}")
            
            # if not comm.empty and 'CUSTOMERID' in comm.columns:
            #     print(f"Corporate CUSTOMERID sample: {comm['CUSTOMERID'].head().tolist()}")
            #     print(f"Corporate non-empty CUSTOMERID count: {comm['CUSTOMERID'].astype(str).ne('').sum()}")
            
            # if not credit_original.empty and 'CUSTOMERID' in credit_original.columns:
            #     print(f"Credit CUSTOMERID sample: {credit_original['CUSTOMERID'].head().tolist()}")
            #     print(f"Credit non-empty CUSTOMERID count: {credit_original['CUSTOMERID'].astype(str).ne('').sum()}")
            
            # Use the original credit DataFrame for corporate merge
            corpo = merge_corporate_borrowers(comm, credit_original, prin)
            
            # Cleanup all merge DataFrames after both individual and corporate merges are complete
            del consu, credit_for_individual, guar, comm, credit_original, prin
            gc.collect()
        
        task.progress = calculate_progress('data_processing', 98)
        task.save()
        
        # Split entities for verification with memory cleanup
        split_indi, split_candidates_commercial = split_commercial_entities(indi)
        split_corpo, split_candidates_consumer = split_consumer_entities(corpo)
        
        # Cleanup original merged dataframes after splitting
        del indi, corpo
        gc.collect()
        
        task.progress = calculate_progress('data_processing', 90)
        task.save()
        
        # Convert int64 values to regular Python integers for JSON serialization
        for stat in processing_stats:
            for key, value in stat.items():
                if hasattr(value, 'item'):  # Check if it's a numpy/pandas scalar
                    stat[key] = value.item()
                elif isinstance(value, (np.int64, np.int32, np.float64, np.float32)):
                    stat[key] = int(value) if 'int' in str(type(value)) else float(value)
        
        # Save intermediate results for user verification
        task.intermediate_data = {
            'split_candidates_commercial': split_candidates_commercial.to_json(orient='split'),
            'split_candidates_consumer': split_candidates_consumer.to_json(orient='split'),
            'indi': split_indi.to_json(orient='split'),
            'corpo': split_corpo.to_json(orient='split'),
            'processing_stats': processing_stats
        }
        
        task.status = 'awaiting_verification'
        task.progress = calculate_progress('data_processing', 100)
        task.save()
        
        # Final memory cleanup
        del processed_sheets, split_indi, split_corpo, split_candidates_commercial, split_candidates_consumer
        gc.collect()
        
    except Exception as e:
        # Remove the original uploaded file even if processing fails
        try:
            original_file_path = os.path.join(settings.MEDIA_ROOT, task.filename)
            if os.path.exists(original_file_path):
                os.remove(original_file_path)
        except Exception as cleanup_error:
            # Log the error but don't fail the entire task
            print(f"Warning: Could not remove original file {task.filename}: {cleanup_error}")
        
        task.status = 'failed'
        task.error_message = str(e)
        task.save()
        raise

def process_verification_decision_background(task_id, commercial_moves, consumer_moves, user_id):
    """
    Background task to process user verification decisions.
    Applies user moves and prepares data for finalization.
    """
    task = FileProcessingTask.objects.get(task_id=task_id)
    
    try:
        task.status = 'processing'
        task.progress = calculate_progress('verification', 10)
        task.save()
        
        # Load data from task intermediate_data
        from io import StringIO
        intermediate_data = task.intermediate_data
        
        split_candidates_commercial = pd.read_json(StringIO(intermediate_data['split_candidates_commercial']), orient='split', dtype=str)
        split_candidates_consumer = pd.read_json(StringIO(intermediate_data['split_candidates_consumer']), orient='split', dtype=str)
        indi = pd.read_json(StringIO(intermediate_data['indi']), orient='split', dtype=str)
        corpo = pd.read_json(StringIO(intermediate_data['corpo']), orient='split', dtype=str)
        processing_stats = intermediate_data.get('processing_stats', [])
        
        task.progress = calculate_progress('verification', 20)
        task.save()
        
        # Apply string enforcement to loaded data
        split_candidates_commercial = enforce_string_columns(split_candidates_commercial)
        split_candidates_consumer = enforce_string_columns(split_candidates_consumer)
        indi = enforce_string_columns(indi)
        corpo = enforce_string_columns(corpo)
        
        task.progress = calculate_progress('verification', 93)
        task.save()
        
        # For commercial candidates: checked = move to corpo, unchecked = stay in indi
        move_to_corp_idx = [i for i, move in enumerate(commercial_moves) if move]
        stay_in_indi_idx = [i for i, move in enumerate(commercial_moves) if not move]

        # Separate checked vs unchecked commercial candidates with IndexError handling
        try:
            checked_commercial = split_candidates_commercial.iloc[move_to_corp_idx].copy() if move_to_corp_idx else pd.DataFrame()
        except (ValueError, IndexError):
            checked_commercial = pd.DataFrame()
            
        try:
            unchecked_commercial = split_candidates_commercial.iloc[stay_in_indi_idx].copy() if stay_in_indi_idx else pd.DataFrame()
        except (ValueError, IndexError):
            unchecked_commercial = pd.DataFrame()

        # For consumer candidates: checked = move to indi, unchecked = stay in corpo
        move_to_indi_idx = [i for i, move in enumerate(consumer_moves) if move]
        stay_in_corp_idx = [i for i, move in enumerate(consumer_moves) if not move]

        # Separate checked vs unchecked consumer candidates with IndexError handling
        try:
            checked_consumer = split_candidates_consumer.iloc[move_to_indi_idx].copy() if move_to_indi_idx else pd.DataFrame()
        except (ValueError, IndexError):
            checked_consumer = pd.DataFrame()
            
        try:
            unchecked_consumer = split_candidates_consumer.iloc[stay_in_corp_idx].copy() if stay_in_corp_idx else pd.DataFrame()
        except (ValueError, IndexError):
            unchecked_consumer = pd.DataFrame()
        
        task.progress = calculate_progress('verification', 94)
        task.save()
        
        # Return unchecked records to original DataFrames (no processing)
        if not unchecked_commercial.empty:
            # Restore original individual name structure for unchecked commercial candidates (VECTORIZED)
            if 'ORIGINAL_BUSINESSNAME' in unchecked_commercial.columns:
                # Vectorized title removal and name splitting using pre-compiled regex
                valid_names_mask = unchecked_commercial['ORIGINAL_BUSINESSNAME'].notna()
                
                if valid_names_mask.any():
                    # Apply vectorized title removal using pre-compiled regex
                    cleaned_names = unchecked_commercial.loc[valid_names_mask, 'ORIGINAL_BUSINESSNAME'].astype(str)
                    cleaned_names = remove_titles_vectorized(cleaned_names)
                    
                    # Vectorized name splitting using str.split with expand=True
                    name_parts = cleaned_names.str.split(n=2, expand=True)
                    name_parts.columns = ['SURNAME', 'FIRSTNAME', 'MIDDLENAME']
                    
                    # Fill missing parts with empty strings
                    name_parts = name_parts.fillna('')
                    
                    # Assign vectorized results using .loc for performance
                    unchecked_commercial.loc[valid_names_mask, 'SURNAME'] = name_parts['SURNAME'].values
                    unchecked_commercial.loc[valid_names_mask, 'FIRSTNAME'] = name_parts['FIRSTNAME'].values
                    unchecked_commercial.loc[valid_names_mask, 'MIDDLENAME'] = name_parts['MIDDLENAME'].values
                    
                    # Memory cleanup
                    del cleaned_names, name_parts, valid_names_mask
                    
                # Remove the temporary ORIGINAL_BUSINESSNAME column using inplace=True
                unchecked_commercial.drop(columns=['ORIGINAL_BUSINESSNAME'], errors='ignore', inplace=True)
            indi = pd.concat([indi, unchecked_commercial], ignore_index=True, copy=False)
        
        if not unchecked_consumer.empty:
            # Restore original business name and clean up individual columns for unchecked consumer records
            if 'ORIGINAL_BUSINESSNAME' in unchecked_consumer.columns:
                unchecked_consumer['BUSINESSNAME'] = unchecked_consumer['ORIGINAL_BUSINESSNAME']
                columns_to_drop = ['ORIGINAL_BUSINESSNAME', 'SURNAME', 'FIRSTNAME', 'MIDDLENAME', 'DEPENDANTS']
                unchecked_consumer = unchecked_consumer.drop(columns=[col for col in columns_to_drop if col in unchecked_consumer.columns], errors='ignore')
            corpo = pd.concat([corpo, unchecked_consumer], ignore_index=True)
        
        task.progress = calculate_progress('verification', 96)
        task.save()
        
        # Transform ONLY checked records
        confirmed_commercial = pd.DataFrame()
        confirmed_consumer = pd.DataFrame()
        
        if not checked_commercial.empty:
            # When moving an individual to commercial:
            confirmed_commercial = transform_to_commercial(
                checked_commercial, 
                columns_to_clear=guarantor_columns_to_clear
            )
            
        if not checked_consumer.empty:
            # When moving a corporate to consumer:
            confirmed_consumer = transform_to_consumer(
                checked_consumer, 
                columns_to_clear=principal_officer_columns_to_clear
            )
        
        task.progress = calculate_progress('verification', 70)
        task.save()
        
        # Concatenate only the transformed checked records
        if not confirmed_consumer.empty:
            indi = pd.concat([indi, confirmed_consumer], ignore_index=True)
        if not confirmed_commercial.empty:
            corpo = pd.concat([corpo, confirmed_commercial], ignore_index=True)

        # All further processing should NOT change dtypes, but just in case:
        indi = modify_middle_names(indi)
        corpo = modify_middle_names(corpo)

        indi = clean_for_output(indi)
        corpo = clean_for_output(corpo)
        
        # Drop name and dependant columns from corpo again to be sure
        columns_to_remove = ['SURNAME', 'FIRSTNAME', 'MIDDLENAME', 'DEPENDANTS']
        corpo = corpo.drop(columns=[col for col in columns_to_remove if col in corpo.columns], errors='ignore')
        
        task.progress = calculate_progress('verification', 98)
        task.save()
        
        # Convert DataFrames to JSON for finalization task
        commercial_df_json = corpo.to_json(orient='split')
        consumer_df_json = indi.to_json(orient='split')
        
        # Queue the finalization task
        async_task(
            finalize_processing_task,
            task.task_id,
            commercial_df_json,
            consumer_df_json,
            task.subscriber_alias,
            user_id
        )
        
        task.status = 'finalizing'  # Transitioning to finalization phase
        task.progress = calculate_progress('finalization', 0)
        task.save()
        
        # Memory management optimization - explicit cleanup with garbage collection
        del split_candidates_commercial, split_candidates_consumer
        del checked_commercial, unchecked_commercial, checked_consumer, unchecked_consumer
        del confirmed_commercial, confirmed_consumer
        del indi, corpo
        gc.collect()  # Force garbage collection for memory optimization
        
    except Exception as e:
        task.status = 'failed'
        task.error_message = str(e)
        task.save()
        raise
    
def finalize_processing_task(task_id, commercial_df_json, consumer_df_json, subscriber_alias, user_id):
    """
    Background task to finalize processing after user verification.
    Performs data manipulation, file generation, and stores results.
    """
    task = FileProcessingTask.objects.get(task_id=task_id)
    
    try:
        task.status = 'finalizing'
        task.progress = calculate_progress('finalization', 0)
        task.save()
        
        # Load the dataframes from JSON
        commercial_df = pd.read_json(commercial_df_json, orient='split')
        consumer_df = pd.read_json(consumer_df_json, orient='split')
        
        task.progress = calculate_progress('finalization', 20)
        task.save()
        
        # Import filename generation utilities
        
        # Generate standardized filenames using subscriber mapping
        individual_filename = generate_filename(subscriber_alias, 'excel', 'consumer')
        corporate_filename = generate_filename(subscriber_alias, 'excel', 'commercial')
        
        individual_txt_filename = generate_filename(subscriber_alias, 'txt', 'consumer')
        corporate_txt_filename = generate_filename(subscriber_alias, 'txt', 'commercial')
        
        # Note: Full files removed for optimization - reduces from 6 to 4 files
        
        # Fallback to timestamp-based naming if mapping fails
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = os.path.splitext(task.filename)[0]
        
        if not individual_filename:
            individual_filename = generate_fallback_filename(base_filename, 'excel', 'consumer', timestamp)
        if not corporate_filename:
            corporate_filename = generate_fallback_filename(base_filename, 'excel', 'commercial', timestamp)
            
        if not individual_txt_filename:
            individual_txt_filename = generate_fallback_filename(base_filename, 'txt', 'consumer', timestamp)
        if not corporate_txt_filename:
            corporate_txt_filename = generate_fallback_filename(base_filename, 'txt', 'commercial', timestamp)
        
        task.progress = calculate_progress('finalization', 30)
        task.save()
        
        # Create organized directory structure (optimized - no full directories)
        excel_dir = os.path.join(settings.MEDIA_ROOT, 'excel')
        excel_individual_dir = os.path.join(excel_dir, 'individual')
        excel_corporate_dir = os.path.join(excel_dir, 'corporate')
        os.makedirs(excel_individual_dir, exist_ok=True)
        os.makedirs(excel_corporate_dir, exist_ok=True)
        
        txt_dir = os.path.join(settings.MEDIA_ROOT, 'txt')
        txt_individual_dir = os.path.join(txt_dir, 'individual')
        txt_corporate_dir = os.path.join(txt_dir, 'corporate')
        os.makedirs(txt_individual_dir, exist_ok=True)
        os.makedirs(txt_corporate_dir, exist_ok=True)
        
        # File paths (optimized - only 4 files instead of 6)
        individual_path = os.path.join(excel_individual_dir, individual_filename)
        corporate_path = os.path.join(excel_corporate_dir, corporate_filename)
        
        individual_txt_path = os.path.join(txt_individual_dir, individual_txt_filename)
        corporate_txt_path = os.path.join(txt_corporate_dir, corporate_txt_filename)
        
        task.progress = calculate_progress('finalization', 40)
        task.save()
        
        # PARALLEL FILE OPERATIONS using ThreadPoolExecutor for 50% performance improvement
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                # Submit all file writing tasks simultaneously
                excel_individual_future = executor.submit(write_excel_file, consumer_df, individual_path)
                excel_corporate_future = executor.submit(write_excel_file, commercial_df, corporate_path)
                txt_individual_future = executor.submit(write_txt_file, consumer_df, individual_txt_path)
                txt_corporate_future = executor.submit(write_txt_file, commercial_df, corporate_txt_path)
                
                # Wait for all tasks to complete with 5-minute timeout
                futures = [excel_individual_future, excel_corporate_future, txt_individual_future, txt_corporate_future]
                
                task.progress = calculate_progress('finalization', 50)
                task.save()
                
                # Collect results with timeout handling
                for future in futures:
                    try:
                        result = future.result(timeout=300)  # 5-minute timeout per file
                        print(f"File operation completed: {result}")
                    except Exception as file_error:
                        raise Exception(f"Parallel file operation failed: {str(file_error)}")
                        
        except Exception as parallel_error:
            # Fallback to sequential processing if parallel fails
            print(f"Parallel processing failed, falling back to sequential: {parallel_error}")
            consumer_df.to_excel(individual_path, index=False, engine='xlsxwriter')
            commercial_df.to_excel(corporate_path, index=False, engine='xlsxwriter')
            consumer_df.to_csv(individual_txt_path, sep='\t', index=False)
            commercial_df.to_csv(corporate_txt_path, sep='\t', index=False)
        
        task.progress = calculate_progress('finalization', 80)
        task.save()
        
        # Calculate statistics
        total_individual = len(consumer_df)
        total_corporate = len(commercial_df)
        
        # Get processing stats from intermediate_data
        processing_stats = task.intermediate_data.get('processing_stats', []) if task.intermediate_data else []
        
        # Generate download URLs using FileSystemStorage (optimized - no full files)
        fs = FileSystemStorage()
        individual_download_url = fs.url(os.path.join('excel', 'individual', individual_filename))
        corporate_download_url = fs.url(os.path.join('excel', 'corporate', corporate_filename))
        
        individual_txt_url = fs.url(os.path.join('txt', 'individual', individual_txt_filename))
        corporate_txt_url = fs.url(os.path.join('txt', 'corporate', corporate_txt_filename))
        
        # Store results data for display_results view (optimized - removed full file URLs)
        task.results_data = {
            'total_individual': total_individual,
            'total_corporate': total_corporate,
            'processing_stats': processing_stats,
            'individual_download_url': individual_download_url,
            'corporate_download_url': corporate_download_url,
            'individual_txt_url': individual_txt_url,
            'corporate_txt_url': corporate_txt_url,
            'success_message': 'File processed and merged successfully!'
        }
        
        # Remove the original uploaded file after successful processing
        try:
            original_file_path = os.path.join(settings.MEDIA_ROOT, task.filename)
            if os.path.exists(original_file_path):
                os.remove(original_file_path)
        except Exception as cleanup_error:
            # Log the error but don't fail the entire task
            print(f"Warning: Could not remove original file {task.filename}: {cleanup_error}")
        
        task.status = 'completed'
        task.progress = calculate_progress('finalization', 100)
        task.save()
        
        # Memory management optimization - explicit cleanup with garbage collection
        del commercial_df, consumer_df
        del individual_filename, corporate_filename, individual_txt_filename, corporate_txt_filename
        del individual_path, corporate_path, individual_txt_path, corporate_txt_path
        gc.collect()  # Force garbage collection for memory optimization
        
    except Exception as e:
        task.status = 'failed'
        task.error_message = str(e)
        task.save()
        raise


