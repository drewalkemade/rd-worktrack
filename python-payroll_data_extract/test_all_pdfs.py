"""
Test script to verify PDF extraction works with all example PDFs
"""

from pdf_parser import PayrollPDFParser
import pandas as pd
from datetime import datetime
import glob

parser = PayrollPDFParser()

# Find all PDF files
pdf_files = sorted(glob.glob("*.pdf"))

print("Testing PDF extraction on all files")
print("=" * 80)

all_results = []

for pdf_file in pdf_files:
    print(f"\nProcessing: {pdf_file}")
    print("-" * 80)

    try:
        employees = parser.parse_payroll_pdf(pdf_file)

        if employees:
            print(f"Extracted {len(employees)} employees:")
            for emp in employees:
                print(f"  {emp['employee_id']:<8} {emp['employee_name']:<30} "
                      f"REG: {emp['reg_hours']:>6.2f}  OT: {emp['ot_hours']:>6.2f}  DBL: {emp['dbl_hours']:>6.2f}")
                all_results.append({
                    'PDF': pdf_file,
                    'Employee_ID': emp['employee_id'],
                    'Employee_Name': emp['employee_name'],
                    'REG': emp['reg_hours'],
                    'OT': emp['ot_hours'],
                    'DBL': emp['dbl_hours']
                })
        else:
            print("  No employees extracted!")

    except Exception as e:
        print(f"  ERROR: {e}")

# Test Excel export format
if all_results:
    print("\n" + "=" * 80)
    print("Testing Excel export format (using first PDF's data)")
    print("=" * 80)

    # Get data from first PDF only
    first_pdf = pdf_files[0]
    employees = parser.parse_payroll_pdf(first_pdf)

    # Create Excel data in the correct format
    ending_date = "11/2/2025"  # Example date
    excel_data = []

    for employee in employees:
        excel_data.append({
            'Ending': ending_date,
            'Employee': employee['employee_id'],     # Employee ID
            'Label': employee['employee_name'],      # Employee Name
            'Hours_1': employee['reg_hours'],        # REG
            'Hours_2': employee['ot_hours'],         # OT
            'Hours_3': employee['dbl_hours'],        # DBL
            'Hours_T': 0                             # Additional column
        })

    df = pd.DataFrame(excel_data)

    # Save to test Excel file
    test_excel = "test_export.xlsx"
    df.to_excel(test_excel, index=False, engine='openpyxl')
    print(f"\nTest Excel file created: {test_excel}")

    # Also save as CSV for easy viewing
    test_csv = "test_export.csv"
    df.to_csv(test_csv, index=False)
    print(f"Test CSV file created: {test_csv}")

    print("\nFirst few rows of export:")
    print(df.head())

    print("\n" + "=" * 80)
    print("Comparing with example.csv format:")
    print("-" * 80)
    print("Expected columns: Ending, Employee, Label, Hours_1, Hours_2, Hours_3, Hours_T")
    print(f"Actual columns:   {', '.join(df.columns.tolist())}")
    print("\nMatch:", df.columns.tolist() == ['Ending', 'Employee', 'Label', 'Hours_1', 'Hours_2', 'Hours_3', 'Hours_T'])
