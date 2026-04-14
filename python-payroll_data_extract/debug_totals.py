"""
Debug script to show employee totals lines
"""

import pdfplumber
import re

pdf_path = "RD_251102-xxxxx.pdf"

employee_line_pattern = r'([A-Z]+(?:-[A-Z]+)?,\s*[A-Z]+)\s+(\d{5})\b'
time_pattern = r'\b\d{1,3}:\d{2}\b'

print("Analyzing employee totals lines")
print("=" * 80)

with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        if not text:
            continue

        lines = text.split('\n')

        for i, line in enumerate(lines):
            employee_match = re.search(employee_line_pattern, line)

            if employee_match:
                name = employee_match.group(1)
                emp_id = employee_match.group(2)

                # Look ahead for totals line
                for j in range(i + 1, min(i + 20, len(lines))):
                    totals_line = lines[j].strip()
                    times = re.findall(time_pattern, totals_line)

                    if len(times) >= 6:
                        non_time_text = re.sub(time_pattern, '', totals_line).strip()

                        if len(non_time_text) < 50:
                            print(f"\nEmployee: {name} (E{int(emp_id)})")
                            print(f"Totals line: {totals_line}")
                            print(f"Time values found: {times}")
                            if len(times) >= 7:
                                print(f"  Position 3 (REG): {times[3]}")
                                print(f"  Position 4 (OT):  {times[4]}")
                                print(f"  Position 5 (DBL): {times[5]}")
                                print(f"  Position 6 (???): {times[6]}")
                            break
