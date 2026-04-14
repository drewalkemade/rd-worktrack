"""
Debug script to look at Jason Latour's data specifically
"""

import pdfplumber

pdf_path = "RD_251102-xxxxx.pdf"

print("Looking for LATOUR, JASON data")
print("=" * 80)

with pdfplumber.open(pdf_path) as pdf:
    all_text = ""

    for page_num, page in enumerate(pdf.pages):
        text = page.extract_text()
        if text:
            print(f"\n--- PAGE {page_num + 1} ---")
            lines = text.split('\n')

            # Find lines with LATOUR
            for i, line in enumerate(lines):
                if 'LATOUR' in line:
                    # Print context: 3 lines before, the line itself, and 10 lines after
                    start = max(0, i - 3)
                    end = min(len(lines), i + 11)

                    print(f"\nFound LATOUR at line {i}:")
                    for j in range(start, end):
                        marker = ">>> " if j == i else "    "
                        print(f"{marker}{lines[j]}")
