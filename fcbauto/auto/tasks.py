import os
import gc
import json
import pandas as pd
import numpy as np
from django.conf import settings
from django_q.tasks import async_task
from .models import FileProcessingTask
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
    consumer_merged_mapping, commercial_merged_mapping
)

def process_large_sheet_chunked(file_path, sheet_name, chunk_size=50000):
    """
    Process large sheets in chunks to reduce memory usage
    """
    processed_chunks = []
    
    # Read sheet in chunks
    for chunk in pd.read_excel(file_path, sheet_name=sheet_name, chunksize=chunk_size, na_filter=False, dtype=str, engine='openpyxl'):
        # Process each chunk
        processed_chunk = process_single_sheet(chunk, sheet_name)
        processed_chunks.append(processed_chunk)
        
        # Cleanup chunk immediately
        del chunk
        gc.collect()
    
    # Combine processed chunks
    final_result = pd.concat(processed_chunks, ignore_index=True)
    
    # Cleanup chunk list
    del processed_chunks
    gc.collect()
    
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

def process_excel_file_background(task_id, file_path, subscriber_alias, user_id):
    """
    Background task to process large Excel files with sequential processing and memory optimization
    Uses all the actual processing functions from views.py
    """
    task = FileProcessingTask.objects.get(id=task_id)
    
    try:
        task.status = 'processing'
        task.progress = 10
        task.save()
        
        # Sequential sheet processing for memory optimization
        # Load sheet names only first
        with pd.ExcelFile(file_path) as excel_file:
            sheet_names = excel_file.sheet_names
        
        task.progress = 15
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
            progress = 20 + (i + 1) * 40 // total_sheets
            task.progress = progress
            task.save()
        
        # Ensure all required sheets exist
        processed_sheets = ensure_all_sheets_exist(processed_sheets)
        
        task.progress = 65
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
        
        task.progress = 80
        task.save()
        
        # Split entities for verification with memory cleanup
        split_indi, split_candidates_commercial = split_commercial_entities(indi)
        split_corpo, split_candidates_consumer = split_consumer_entities(corpo)
        
        # Cleanup original merged dataframes after splitting
        del indi, corpo
        gc.collect()
        
        task.progress = 90
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
        task.progress = 100
        task.save()
        
        # Final memory cleanup
        del processed_sheets, split_indi, split_corpo, split_candidates_commercial, split_candidates_consumer
        gc.collect()
        
    except Exception as e:
        task.status = 'failed'
        task.error_message = str(e)
        task.save()
        raise