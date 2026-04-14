# Payroll & Timesheet Data Extractor

A Python GUI application with a tabbed interface that extracts employee data from both PDF payroll reports and Excel timesheets, then exports to CSV format.

## Overview

The application features two extraction tools in a tabbed interface:
1. **Payroll PDF Extractor** - Extracts data from weekly PDF payroll reports
2. **Timesheet Extractor** - Bulk extracts data from Excel (.xlsx) timesheet files

## Features

### General Features
- **Tabbed GUI Interface** - User-friendly interface with separate tabs for each tool
- **Data Preview** - View extracted data in tables before exporting
- **CSV Export** - Export data to CSV with date-based filenames
- **Error Handling** - Warning messages for extraction issues
- **Batch Processing** - Process multiple files at once (timesheets)

### Payroll PDF Extractor
- Extracts employee payroll data from PDF reports
- Converts HH:MM time format to decimal hours
- Handles employees spanning multiple pages
- Customizable pay period ending date

### Timesheet Extractor
- Bulk processes multiple Excel timesheet files
- Extracts data from 'Biweekly Time Sheet' sheets
- Automatically sorts by employee name order
- Uses end date from timesheet for filename

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

### Setup

1. Clone or download this repository

2. Install required dependencies:

```bash
pip install -r requirements.txt
```

The required packages are:
- `pdfplumber` - For PDF text extraction
- `openpyxl` - For Excel file reading
- `pandas` - For data manipulation
- `tkcalendar` - For date picker widget
- `Pillow` - Image processing (required by tkinter)

## Usage

### Running the Application

Enter venv:
```bash
.\venv\Scripts\activate
```

Start the application:

```bash
python payroll_extractor.py
```

The GUI will open with two tabs: **Payroll PDF Extractor** and **Timesheet Extractor**.

---

## Tab 1: Payroll PDF Extractor

### Extracted Data

The payroll extractor extracts the following information for each employee:

- Employee ID (e.g., E8022)
- Employee Name (e.g., Atkinson, Jeremy)
- REG hours (regular hours)
- OT hours (overtime hours)
- DBL hours (double time hours)

### Step-by-Step Guide

**Step 1: Select PDF File**
- Click the "Browse PDF File..." button
- Select your payroll PDF report
- The filename will be displayed once selected

**Step 2: Extract Data**
- Click the "Extract Data" button
- The application will parse the PDF and extract employee payroll information
- Extracted data will be displayed in the preview table

**Step 3: Set Pay Period Ending Date**
- Use the date picker to select the pay period ending date
- Default is today's date

**Step 4: Export to CSV**
- Click the "Export to CSV" button
- Choose where to save the CSV file
- Default filename: `payroll_export_YYYYMMDD.csv` (e.g., `payroll_export_20251116.csv`)

### CSV Output Format

The exported CSV file contains the following columns:

| Ending | Employee | Label | Hours_1 (REG) | Hours_2 (OT) | Hours_3 (DBL) | Hours_T |
|--------|----------|-------|---------------|--------------|---------------|---------|
| 11/16/2025 | E8022 | Atkinson, Jeremy | 40.0 | 4.5 | 0.0 | 0 |

### PDF Format Requirements

The application is designed to work with "Payroll and Attendance Approval Report" PDFs that have:

- Employee names and IDs in format: "LASTNAME, FIRSTNAME 08022" (5-digit ID)
- Daily time entries for each employee
- A totals line with multiple time values in HH:MM format
- The totals line contains REG, OT, and DBL hours at specific positions

#### Example PDF Structure

```
ATKINSON, JEREMY 08022 Mon, Oct 27 DAY 6AM CL415...
Tue, Oct 28 DAY 6AM CL415...
...
44:30 44:30 44:30 40:00 4:30 0:00 0:00 44:30 44:30
```

The totals line format:
- Positions 0-2: Attendance totals (repeated)
- **Position 3: REG hours** (e.g., 40:00)
- **Position 4: OT hours** (e.g., 4:30)
- **Position 5: DBL hours** (e.g., 0:00)
- Position 6: Other hours
- Positions 7-8: Overall totals

The application extracts positions 3, 4, and 5 for REG, OT, and DBL hours respectively.

### Time Conversion

The application automatically converts time from HH:MM format to decimal hours:

- `40:00` → 40.0 hours
- `8:30` → 8.5 hours
- `44:45` → 44.75 hours
- `0:00` → 0.0 hours

---

## Tab 2: Timesheet Extractor

### Extracted Data

The timesheet extractor extracts the following information from each Excel file:

- Employee Name (from cell H3)
- End Date (from cell H5)
- Regular Hours (column D, row 23)
- Overtime 1 Hours (column E, row 23)
- Overtime 2 Hours (column F, row 23)
- Drive Hours (column G, row 23)
- Sick/PEL (column H, row 23)
- Vacation (column I, row 23)
- Holiday (column J, row 23)
- Non-Billable (column K, row 23)

### Step-by-Step Guide

**Step 1: Select Timesheet Files**
- Click the "Browse Files..." button
- Select one or more Excel timesheet files (.xlsx)
- Selected files will be listed in the file list
- Use "Clear" button to remove selections if needed

**Step 2: Extract Data**
- Click the "Extract Data" button
- The application will process all selected timesheets
- Extracted data will be displayed in the preview table
- Warning messages will appear if any files have issues

**Step 3: Export to CSV**
- Click the "Export to CSV" button
- Choose where to save the CSV file
- Default filename: `timesheet_export_YYYYMMDD.csv` (e.g., `timesheet_export_20251123.csv`)
- Date is automatically taken from the timesheets (cell H5)

### CSV Output Format

The exported CSV file contains the following columns:

| Ending | Employee | Label | Hours_1 | Hours_2 | Hours_3 | Hours_4 | Hours_5 | Hours_6 | Hours_7 | Hours_8 |
|--------|----------|-------|---------|---------|---------|---------|---------|---------|---------|---------|
| 11/23/2025 | Daniel Trif | Hours | 80.0 | 9.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Column mapping:
- **Hours_1**: Regular Hours
- **Hours_2**: Overtime 1 Hours
- **Hours_3**: Overtime 2 Hours
- **Hours_4**: Drive Hours
- **Hours_5**: Sick/PEL
- **Hours_6**: Vacation
- **Hours_7**: Holiday
- **Hours_8**: Non-Billable

### Excel Format Requirements

Timesheet files must be Excel (.xlsx) format with:

- A sheet named **'Biweekly Time Sheet'**
- **Cell H3**: Employee name (e.g., "Daniel Trif")
- **Cell H5**: End date (used for CSV filename)
- **Row 23**: Total hours for each category

#### Required Columns in Row 23

| Column | Label | Description |
|--------|-------|-------------|
| D23 | Regular Hours | Regular work hours |
| E23 | Overtime 1 Hours | First overtime rate |
| F23 | Overtime 2 Hours | Second overtime rate |
| G23 | Drive Hours | Travel/drive time |
| H23 | Sick/PEL | Sick leave hours |
| I23 | Vacation | Vacation hours |
| J23 | Holiday | Holiday hours |
| K23 | Non-Billable | Non-billable hours |

### Employee Sort Order

Exported data is automatically sorted in this order:
1. Daniel Trif
2. Jerry Jeremias
3. Paul Robertson
4. Zachary Ebbinghaus
5. Florin Moldovan
6. Jarrett Zorzi
7. Yousof Saleh

To modify the sort order, edit the `name_order` list in `payroll_extractor.py` (TimesheetTab class, line 203).

---

## Testing and Debugging

### PDF Debug Scripts

**Debug a specific PDF:**
```bash
python debug_pdf.py RD_251102-xxxxx.pdf
```
Shows the raw text and table structure from the PDF.

**Test the PDF parser:**
```bash
python test_parser.py
```
Tests extraction on the first PDF and compares with expected values.

**Test all PDFs:**
```bash
python test_all_pdfs.py
```
Extracts data from all PDFs and creates test CSV files.

### Timesheet Debug Scripts

**Debug timesheet structure:**
```bash
python debug_timesheet2.py
```
Shows cell values from all timesheet files.

**Test timesheet extraction:**
```bash
python test_timesheet_extraction.py
```
Extracts data from all timesheets and creates test CSV.

---

## Code Structure

```
python-payroll_data_extract/
├── payroll_extractor.py        # Main GUI application (tabbed interface)
├── pdf_parser.py                # PDF parsing logic
├── timesheet_extractor.py       # Excel timesheet parsing logic
├── requirements.txt             # Python dependencies
├── example.csv                  # Example payroll CSV output
├── example_ts.csv               # Example timesheet CSV output
├── debug_*.py                   # Debug scripts
├── test_*.py                    # Test scripts
└── README.md                    # This file
```

### payroll_extractor.py
Contains the main GUI application with tabbed interface:
- `MainApplication` - Manages tabs and window
- `PayrollPDFTab` - PDF extraction tab
- `TimesheetTab` - Timesheet extraction tab

### pdf_parser.py
Contains the PDF parsing logic:
- `PayrollPDFParser` class - Main PDF parser
- `time_to_decimal()` - Time format conversion
- `extract_employee_info()` - Text-based extraction
- `extract_from_table()` - Table-based extraction
- `parse_payroll_pdf()` - Main parsing method

### timesheet_extractor.py
Contains the Excel timesheet parsing logic:
- `TimesheetExtractor` class - Main timesheet parser
- `extract_timesheet()` - Single file extraction
- `extract_multiple_timesheets()` - Batch processing
- `sort_by_name_order()` - Custom name sorting

---

## Troubleshooting

### Payroll PDF Issues

**No Data Extracted:**
1. **Check PDF format** - Ensure the PDF matches the expected structure
2. **Verify text extraction** - Some PDFs are image-based and require OCR
3. **Check for encryption** - Encrypted PDFs may not be readable

**Parsing Errors:**
1. **Review PDF structure** - The PDF format may differ from expected
2. **Modify patterns** - Update regular expressions in `pdf_parser.py`
3. **Check employee ID format** - Modify `employee_id_pattern` if needed

### Timesheet Issues

**No Data Extracted:**
1. **Check sheet name** - Must be exactly 'Biweekly Time Sheet'
2. **Verify cell locations** - Name in H3, date in H5
3. **Check row 23** - Totals must be in row 23

**Incorrect Data:**
1. **Check formulas** - Ensure row 23 formulas are calculating correctly
2. **Verify date format** - Cell H5 must contain a valid date
3. **Check file format** - Must be .xlsx (not .xls or .xlsm)

**Sort Order Issues:**
1. **Name matching** - Names must exactly match the sort order list
2. **Modify sort order** - Edit `name_order` in `payroll_extractor.py`

### Common Error Messages

- **"No file selected"** - Select a file/files before extracting
- **"No data found"** - File format not recognized or no data found
- **"Failed to extract data"** - Error during parsing (check file format)
- **"Sheet 'Biweekly Time Sheet' not found"** - Excel file missing required sheet
- **"No name found in cell H3"** - Cell H3 is empty or invalid
- **"No end date found in cell H5"** - Cell H5 is empty or invalid

---

## License

This project is open source and available for modification and distribution.

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## Support

For issues or questions:
1. Check the Troubleshooting section
2. Review the format requirements (PDF or Excel)
3. Verify all dependencies are installed correctly
4. Run the appropriate debug scripts

## Future Enhancements

Possible improvements:
- Support for multiple PDF formats
- OCR support for image-based PDFs
- Custom field mapping for timesheets
- Data validation rules
- Summary statistics and reports
- Direct import to accounting systems
