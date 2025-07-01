# FCB Auto - Financial Credit Bureau Data Processing System

A Django-based web application designed to automate the processing and standardization of financial data for credit reporting purposes. This system handles Excel file uploads containing borrower information and transforms them into standardized formats suitable for credit bureau reporting.

## 🚀 Features

### Core Functionality
- **Excel File Processing**: Upload and process Excel files containing financial/borrower data
- **Data Standardization**: Automatically maps and standardizes column headers using fuzzy matching
- **Multi-Sheet Support**: Handles multiple worksheet types including:
  - Individual Borrower Templates
  - Corporate Borrower Templates
  - Credit Information
  - Guarantors Information
  - Principal Officers Templates
  - Consumer/Commercial Merged sheets

### Data Processing Capabilities
- **Intelligent Column Mapping**: Uses fuzzy string matching (RapidFuzz) to map various column header formats to standardized field names
- **Data Cleaning**: Removes special characters, handles null values, and standardizes data formats
- **Date Extraction**: Automatically extracts dates from filenames in various formats (YYYY_MM_DD, Month_Year, etc.)
- **Subscriber Alias Detection**: Extracts subscriber information from uploaded filenames
- **Missing Sheet Generation**: Automatically creates missing required sheets with appropriate headers

### File Output
- **Multiple Format Support**: Generates output files in both Excel (.xlsx) and Tab-separated (.txt) formats
- **Organized Storage**: Separates files into individual, corporate, and combined categories
- **Cross-Platform Compatibility**: Ensures consistent line endings across different operating systems

### Security & Authentication
- **User Authentication**: Login/logout functionality with Django's built-in authentication
- **Access Control**: Login required for file processing operations
- **Secure File Handling**: Proper file storage and management

## 🏗️ Technical Architecture

### Technology Stack
- **Backend**: Django 5.1.3
- **Data Processing**: Pandas, NumPy
- **String Matching**: RapidFuzz for fuzzy column matching
- **Date Processing**: dateparser, word2number
- **Frontend**: Django Templates with HTML forms
- **Database**: SQLite (development)

### Project Structure
```
fcbauto/
├── fcbauto/                 # Main Django project
│   ├── settings.py         # Project settings
│   ├── urls.py             # Main URL configuration
│   └── wsgi.py             # WSGI configuration
├── auto/                    # Core data processing app
│   ├── views.py            # Main processing logic
│   ├── forms.py            # File upload forms
│   ├── map.py              # Column mapping dictionaries
│   ├── mappings.py         # Additional mapping utilities
│   ├── filename_utils.py   # Filename processing utilities
│   ├── templates/          # HTML templates
│   └── static/             # Static files (CSS, JS)
├── acctmgt/                 # Account management app
│   ├── views.py            # Authentication views
│   └── urls.py             # Authentication URLs
├── media/                   # File storage
│   ├── excel/              # Uploaded Excel files
│   └── txt/                # Generated text files
└── manage.py               # Django management script
```

## 📊 Supported Data Types

### Individual Borrower Information
- Customer identification (ID, BVN, NIN, etc.)
- Personal details (name, DOB, gender, marital status)
- Contact information (address, phone, email)
- Employment details
- Financial information

### Corporate Borrower Information
- Company identification and registration details
- Business information and classification
- Corporate structure and ownership
- Financial data and credit history

### Credit Information
- Loan details and facility information
- Repayment history and status
- Collateral information
- Credit classification and ratings

### Guarantor Information
- Guarantor personal/corporate details
- Guarantee amounts and terms
- Relationship to borrower

### Principal Officers
- Officer identification and roles
- Personal information
- Relationship to corporate entity

## 🔧 Installation & Setup

### Prerequisites
- Python 3.8+
- pip (Python package manager)

### Installation Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd fccbmain
   ```

2. **Create virtual environment**
   ```bash
   python -m venv myenv
   myenv\Scripts\activate  # Windows
   # or
   source myenv/bin/activate  # Linux/Mac
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Navigate to project directory**
   ```bash
   cd fcbauto
   ```

5. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

6. **Create superuser (optional)**
   ```bash
   python manage.py createsuperuser
   ```

7. **Start development server**
   ```bash
   python manage.py runserver
   ```

8. **Access the application**
   - Open browser and navigate to `http://127.0.0.1:8000/`
   - Login at `http://127.0.0.1:8000/acctmgt/login/`

## 📝 Usage

### File Upload Process
1. **Login**: Access the system using your credentials
2. **Upload File**: Select and upload an Excel file containing borrower data
3. **Processing**: The system automatically:
   - Analyzes sheet structure
   - Maps column headers to standard format
   - Cleans and validates data
   - Generates missing sheets if needed
4. **Download**: Retrieve processed files in both Excel and text formats

### Supported File Formats
- **Input**: Excel files (.xlsx, .xls) with multiple worksheets
- **Output**: 
  - Excel files (.xlsx) with standardized structure
  - Tab-separated text files (.txt) for each category

### File Naming Conventions
The system automatically extracts information from filenames:
- **Date formats**: YYYY_MM_DD, Month_Year, Year_Month
- **Subscriber alias**: Automatically detected by removing date patterns
- **Examples**: 
  - `bank_name_2024_03_31.xlsx` → Subscriber: "bank_name", Date: March 2024
  - `credit_union_may_2024.xlsx` → Subscriber: "credit_union", Date: May 2024

## 🔍 Data Mapping

The system uses intelligent fuzzy matching to map various column header formats to standardized field names. For example:

- **Customer ID**: Maps from "customerid", "customer_number", "cust_id", "id_no", etc.
- **Full Name**: Maps from "surname", "full_name", "customer_name", "business_name", etc.
- **Date of Birth**: Maps from "dob", "birth_date", "date_of_birth", "birthday", etc.

## 🛠️ Configuration

### Key Settings
- **File Storage**: Configured in `settings.py` under `MEDIA_ROOT`
- **Column Mappings**: Defined in `auto/map.py`
- **Authentication**: Standard Django authentication system

### Customization
- **Add new mappings**: Edit `auto/map.py` to include new column variations
- **Modify processing logic**: Update `auto/views.py` for custom data processing
- **Change templates**: Modify files in `auto/templates/` for UI customization

## 🔒 Security Features

- **Authentication Required**: All file processing requires user login
- **Secure File Handling**: Files are stored securely with proper access controls
- **Data Validation**: Input validation and sanitization
- **CSRF Protection**: Built-in Django CSRF protection

## 📈 Performance

- **Efficient Processing**: Uses pandas for fast data manipulation
- **Memory Management**: Handles large Excel files efficiently
- **Batch Processing**: Processes multiple sheets simultaneously
- **Optimized Matching**: Fast fuzzy string matching with RapidFuzz

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

[Add your license information here]

## 📞 Support

For support and questions:
- Create an issue in the repository
- Contact the development team
- Check the documentation for troubleshooting

---

**Note**: This system is designed for financial institutions and credit bureaus to standardize and process borrower data for credit reporting purposes. Ensure compliance with relevant data protection and financial regulations in your jurisdiction.