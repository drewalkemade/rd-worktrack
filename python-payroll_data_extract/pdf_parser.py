"""
PDF Parser for Payroll Reports
Extracts employee payroll data from PDF reports
"""

import re
import pdfplumber
from typing import List, Dict, Optional


class PayrollPDFParser:
    """Parser for payroll PDF reports"""

    def __init__(self):
        """Initialize the parser"""
        # Regular expressions for parsing
        # Employee ID is 5 digits (like 08022) without "E" prefix in the PDF
        self.employee_id_pattern = r'\b0\d{4}\b'  # Matches 08022, 08031, etc.
        self.time_pattern = r'\b\d{1,3}:\d{2}\b'  # Matches HH:MM format like 40:00, 8:30
        # Pattern for employee name followed by ID
        # Format: "LASTNAME, FIRSTNAME 08022"
        self.employee_line_pattern = r'([A-Z]+(?:-[A-Z]+)?,\s*[A-Z]+)\s+(\d{5})\b'

    def time_to_decimal(self, time_str: str) -> float:
        """
        Convert time from HH:MM format to decimal hours

        Args:
            time_str: Time string in HH:MM format (e.g., "40:00", "8:30")

        Returns:
            Decimal hours (e.g., 40.0, 8.5)
        """
        if not time_str or time_str.strip() == "" or time_str == "0:00":
            return 0.0

        try:
            # Handle the format "HH:MM"
            time_str = time_str.strip()
            parts = time_str.split(':')

            if len(parts) != 2:
                return 0.0

            hours = int(parts[0])
            minutes = int(parts[1])

            # Convert to decimal
            decimal_hours = hours + (minutes / 60.0)
            return round(decimal_hours, 2)

        except (ValueError, AttributeError):
            return 0.0

    def extract_employee_info(self, text: str) -> List[Dict[str, any]]:
        """
        Extract employee information from PDF text

        Args:
            text: Raw text extracted from PDF

        Returns:
            List of dictionaries containing employee payroll data
        """
        employees = []
        lines = text.split('\n')

        current_employee_id = None
        current_employee_name = None

        for i, line in enumerate(lines):
            line = line.strip()

            # Look for employee line pattern: "LASTNAME, FIRSTNAME 08022 Mon, Oct 27..."
            employee_match = re.search(self.employee_line_pattern, line)

            if employee_match:
                # Extract name and ID
                current_employee_name = employee_match.group(1)
                current_employee_id = employee_match.group(2)  # 5-digit ID like 08022

                # Now look for the totals line for this employee
                # The totals line appears after the daily entries
                # Format: "44:30 44:30 44:30 40:00 4:30 0:00 0:00 44:30 44:30"
                # Positions: [0]    [1]    [2]    [3]REG [4]OT [5]DBL [6]   [7]    [8]

                # Look ahead for the totals line (within next 20 lines)
                for j in range(i + 1, min(i + 20, len(lines))):
                    totals_line = lines[j].strip()

                    # Find all time values in this line
                    times = re.findall(self.time_pattern, totals_line)

                    # The totals line typically has 7-9 time values
                    # We need positions 3, 4, 5 for REG, OT, DBL
                    if len(times) >= 6:
                        # Check if this looks like a totals line
                        # It should have multiple time values and minimal other text
                        # Remove all time patterns and see what's left
                        non_time_text = re.sub(self.time_pattern, '', totals_line).strip()

                        # If mostly time values (little other text), this is likely the totals line
                        if len(non_time_text) < 50:  # Adjust threshold as needed
                            try:
                                # Extract REG (position 3), OT (position 4), DBL (position 5)
                                # Note: Arrays are 0-indexed, so position 3 is times[3]
                                reg_hours = self.time_to_decimal(times[3]) if len(times) > 3 else 0.0
                                ot_hours = self.time_to_decimal(times[4]) if len(times) > 4 else 0.0
                                dbl_hours = self.time_to_decimal(times[5]) if len(times) > 5 else 0.0

                                # Add employee with E prefix and remove leading zero from ID
                                # Convert 08022 -> E8022
                                employee_id_int = int(current_employee_id)  # Converts "08022" to 8022
                                formatted_id = f'E{employee_id_int}'  # Creates "E8022"

                                # Convert name to title case
                                formatted_name = current_employee_name.title()

                                employees.append({
                                    'employee_id': formatted_id,
                                    'employee_name': formatted_name,
                                    'reg_hours': reg_hours,
                                    'ot_hours': ot_hours,
                                    'dbl_hours': dbl_hours
                                })

                                # Reset for next employee
                                current_employee_id = None
                                current_employee_name = None
                                break  # Found totals, move to next employee

                            except (IndexError, ValueError):
                                continue

        return employees

    def extract_from_table(self, page) -> List[Dict[str, any]]:
        """
        Alternative extraction method using table detection

        Args:
            page: pdfplumber page object

        Returns:
            List of employee data dictionaries
        """
        employees = []

        try:
            tables = page.extract_tables()

            for table in tables:
                if not table:
                    continue

                # Look for table headers to identify column positions
                header_row = None
                for i, row in enumerate(table):
                    if row and any('employee' in str(cell).lower() if cell else False for cell in row):
                        header_row = i
                        break

                if header_row is None:
                    continue

                headers = [str(cell).strip().lower() if cell else '' for cell in table[header_row]]

                # Find column indices
                id_col = next((i for i, h in enumerate(headers) if 'id' in h or 'employee' in h), None)
                name_col = next((i for i, h in enumerate(headers) if 'name' in h), None)
                reg_col = next((i for i, h in enumerate(headers) if 'reg' in h), None)
                ot_col = next((i for i, h in enumerate(headers) if 'ot' in h or 'overtime' in h), None)
                dbl_col = next((i for i, h in enumerate(headers) if 'dbl' in h or 'double' in h), None)

                # Process data rows
                for row in table[header_row + 1:]:
                    if not row or not any(row):
                        continue

                    # Extract employee ID
                    employee_id = None
                    if id_col is not None and row[id_col]:
                        id_match = re.search(self.employee_id_pattern, str(row[id_col]))
                        if id_match:
                            employee_id = id_match.group(0)

                    # If no ID column, search all columns
                    if not employee_id:
                        for cell in row:
                            if cell:
                                id_match = re.search(self.employee_id_pattern, str(cell))
                                if id_match:
                                    employee_id = id_match.group(0)
                                    break

                    if not employee_id:
                        continue

                    # Extract name
                    employee_name = ""
                    if name_col is not None and row[name_col]:
                        employee_name = str(row[name_col]).strip()

                    # Extract hours
                    reg_hours = 0.0
                    ot_hours = 0.0
                    dbl_hours = 0.0

                    if reg_col is not None and row[reg_col]:
                        reg_hours = self.time_to_decimal(str(row[reg_col]))
                    if ot_col is not None and row[ot_col]:
                        ot_hours = self.time_to_decimal(str(row[ot_col]))
                    if dbl_col is not None and row[dbl_col]:
                        dbl_hours = self.time_to_decimal(str(row[dbl_col]))

                    employees.append({
                        'employee_id': employee_id,
                        'employee_name': employee_name,
                        'reg_hours': reg_hours,
                        'ot_hours': ot_hours,
                        'dbl_hours': dbl_hours
                    })

        except Exception as e:
            print(f"Error extracting from table: {e}")

        return employees

    def parse_payroll_pdf(self, pdf_path: str) -> List[Dict[str, any]]:
        """
        Main method to parse payroll PDF

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of employee payroll data dictionaries
        """
        all_employees = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Extract text from ALL pages first to handle employees spanning multiple pages
                all_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        all_text += text + "\n"

                # Parse the combined text (handles cross-page employees)
                if all_text:
                    text_employees = self.extract_employee_info(all_text)
                    all_employees.extend(text_employees)

                # If text extraction didn't work well, try table extraction as fallback
                if not all_employees:
                    for page in pdf.pages:
                        table_employees = self.extract_from_table(page)
                        if table_employees:
                            all_employees.extend(table_employees)

            # Remove duplicates based on employee_id
            seen_ids = set()
            unique_employees = []
            for emp in all_employees:
                if emp['employee_id'] not in seen_ids:
                    seen_ids.add(emp['employee_id'])
                    unique_employees.append(emp)

            return unique_employees

        except Exception as e:
            raise Exception(f"Error parsing PDF: {str(e)}")


# Testing function
if __name__ == "__main__":
    # Test time conversion
    parser = PayrollPDFParser()

    print("Testing time conversion:")
    print(f"40:00 -> {parser.time_to_decimal('40:00')}")  # Should be 40.0
    print(f"8:30 -> {parser.time_to_decimal('8:30')}")    # Should be 8.5
    print(f"44:45 -> {parser.time_to_decimal('44:45')}")  # Should be 44.75
    print(f"0:00 -> {parser.time_to_decimal('0:00')}")    # Should be 0.0
