"""
Quick test script for the PDF parser
"""

from pdf_parser import PayrollPDFParser

# Test with the actual PDF
parser = PayrollPDFParser()

print("Testing PDF extraction with RD_251102-xxxxx.pdf")
print("=" * 80)

try:
    employees = parser.parse_payroll_pdf("RD_251102-xxxxx.pdf")

    print(f"\nExtracted {len(employees)} employees:\n")

    for emp in employees:
        print(f"ID: {emp['employee_id']:<10} Name: {emp['employee_name']:<25} "
              f"REG: {emp['reg_hours']:>6.2f}  OT: {emp['ot_hours']:>6.2f}  DBL: {emp['dbl_hours']:>6.2f}")

    print("\n" + "=" * 80)
    print("Expected values from example.csv:")
    print("E8022  Atkinson, Jeremy       REG: 40.00  OT: 4.50  DBL: 0.00")
    print("E8031  Wiseman, Jeremy         REG: 40.00  OT: 1.25  DBL: 0.00")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
