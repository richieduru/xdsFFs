# Filename Generation Utilities for Standardized Naming Convention
# Based on task4.md specifications

from datetime import datetime, timedelta
from calendar import monthrange
from .map import subscriber_mappings

def get_subscriber_info(alias):
    """
    Get subscriber information from alias using the existing subscriber_mappings
    
    Args:
        alias (str): Subscriber alias/short name
    
    Returns:
        tuple: (subid, subscriber_name) or (None, None) if not found
    """
    # Search through subscriber_mappings to find matching alias
    for (subid, subscriber_name), aliases in subscriber_mappings.items():
        if alias in aliases or alias.lower() in [a.lower() for a in aliases]:
            return subid, subscriber_name
    return None, None

def get_last_day_of_month(year, month):
    """
    Get the last day of a given month and year
    
    Args:
        year (int): Year
        month (int): Month (1-12)
        
    Returns:
        str: Date in YYYYMMDD format
    """
    last_day = monthrange(year, month)[1]
    return f"{year:04d}{month:02d}{last_day:02d}"

def get_date_for_filename(assigned_month=None, assigned_year=None):
    """
    Get the date to use in filename based on assigned month/year or default to previous month
    
    Args:
        assigned_month (int, optional): Assigned month (1-12)
        assigned_year (int, optional): Assigned year
        
    Returns:
        str: Date in YYYYMMDD format (last day of the month)
    """
    if assigned_month and assigned_year:
        return get_last_day_of_month(assigned_year, assigned_month)
    else:
        # Default to last day of previous month
        today = datetime.now()
        if today.month == 1:
            prev_month = 12
            prev_year = today.year - 1
        else:
            prev_month = today.month - 1
            prev_year = today.year
        return get_last_day_of_month(prev_year, prev_month)

def get_month_year_string(assigned_month=None, assigned_year=None):
    """
    Get month and year strings for filename
    
    Args:
        assigned_month (int, optional): Assigned month (1-12)
        assigned_year (int, optional): Assigned year
        
    Returns:
        tuple: (month_name, year_string)
    """
    month_names = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ]
    
    if assigned_month and assigned_year:
        month_name = month_names[assigned_month - 1]
        year_string = str(assigned_year)
    else:
        # Default to previous month
        today = datetime.now()
        if today.month == 1:
            prev_month = 12
            prev_year = today.year - 1
        else:
            prev_month = today.month - 1
            prev_year = today.year
        month_name = month_names[prev_month - 1]
        year_string = str(prev_year)
    
    return month_name, year_string

def get_type_digit(file_type, borrower_type):
    """
    Get the type digit based on file type and borrower type
    
    Args:
        file_type (str): 'excel' or 'txt'
        borrower_type (str): 'consumer' or 'commercial'
        
    Returns:
        str: Type digit
    """
    type_mapping = {
        ('excel', 'consumer'): '1',
        ('excel', 'commercial'): '2',
        ('txt', 'consumer'): '17',
        ('txt', 'commercial'): '18'
    }
    
    key = (file_type.lower(), borrower_type.lower())
    return type_mapping.get(key, '1')  # Default to '1' if not found

def generate_filename(alias, file_type, borrower_type, assigned_month=None, assigned_year=None):
    """
    Generate standardized filename according to task4.md specifications
    
    Args:
        alias (str): Subscriber alias/short name
        file_type (str): 'excel' or 'txt'
        borrower_type (str): 'consumer' or 'commercial'
        assigned_month (int, optional): Assigned month (1-12)
        assigned_year (int, optional): Assigned year
        
    Returns:
        str: Generated filename or None if alias not found
    """
    # Get subscriber information
    subid, subscriber_name = get_subscriber_info(alias)
    
    if not subid or not subscriber_name:
        # Handle error gracefully - return None or raise exception
        print(f"Warning: Subscriber alias '{alias}' not found in mapping")
        return None
    
    # Get date components
    date_string = get_date_for_filename(assigned_month, assigned_year)
    month_name, year_string = get_month_year_string(assigned_month, assigned_year)
    
    # Get type digit
    type_digit = get_type_digit(file_type, borrower_type)
    
    # Determine borrower type string and file extension
    borrower_type_str = 'Consumer' if borrower_type.lower() == 'consumer' else 'Commercial'
    file_extension = '.xlsx' if file_type.lower() == 'excel' else '.txt'
    
    # Construct filename according to specification
    # Format: SUBID_YYYYMMDD_TypeDigit_SUBSCRIBERNAME_Month_Year_BorrowerType.extension
    filename = f"{subid}_{date_string}_{type_digit}_{subscriber_name}_{month_name}_{year_string}_{borrower_type_str}{file_extension}"
    
    return filename

def generate_fallback_filename(original_filename, file_type, borrower_type, timestamp=None):
    """
    Generate fallback filename when subscriber mapping fails
    
    Args:
        original_filename (str): Original uploaded filename
        file_type (str): 'excel' or 'txt'
        borrower_type (str): 'consumer' or 'commercial'
        timestamp (str, optional): Timestamp string
        
    Returns:
        str: Fallback filename
    """
    if not timestamp:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    borrower_type_str = 'individual' if borrower_type.lower() == 'consumer' else 'corporate'
    file_extension = '.xlsx' if file_type.lower() == 'excel' else '.txt'
    
    return f"{original_filename}_{borrower_type_str}_borrowers_{timestamp}{file_extension}"