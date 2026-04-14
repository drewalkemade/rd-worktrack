"""
Debug script to analyze PDF structure and content
Run this to see what's in your PDF file
"""

import pdfplumber
import sys

def debug_pdf(pdf_path):
    """Print detailed information about PDF content"""

    print("=" * 80)
    print(f"Analyzing PDF: {pdf_path}")
    print("=" * 80)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"\nTotal pages: {len(pdf.pages)}")

            for page_num, page in enumerate(pdf.pages):
                print(f"\n{'=' * 80}")
                print(f"PAGE {page_num + 1}")
                print(f"{'=' * 80}")

                # Extract and display text
                text = page.extract_text()
                if text:
                    print("\n--- RAW TEXT ---")
                    print(text[:2000])  # First 2000 characters
                    if len(text) > 2000:
                        print(f"\n... (truncated, total length: {len(text)} characters)")
                else:
                    print("\n--- NO TEXT FOUND ---")

                # Try to extract tables
                print("\n--- TABLE DETECTION ---")
                tables = page.extract_tables()
                if tables:
                    print(f"Found {len(tables)} table(s)")
                    for i, table in enumerate(tables):
                        print(f"\nTable {i + 1}:")
                        print(f"Rows: {len(table)}")
                        if table:
                            print("First few rows:")
                            for j, row in enumerate(table[:5]):
                                print(f"  Row {j}: {row}")
                else:
                    print("No tables detected")

                print("\n")

    except Exception as e:
        print(f"\nError analyzing PDF: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_pdf.py <path_to_pdf_file>")
        print("\nOr drag and drop a PDF file onto this script")
        sys.exit(1)

    pdf_path = sys.argv[1]
    debug_pdf(pdf_path)
