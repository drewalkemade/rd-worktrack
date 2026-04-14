"""
Test script for timesheet extraction
"""

from timesheet_extractor import TimesheetExtractor
import pandas as pd
import glob

def test_extraction():
    print("Testing Timesheet Extraction")
    print("=" * 80)

    extractor = TimesheetExtractor()

    # Get all timesheet files
    timesheet_files = sorted(glob.glob("*.xlsx"))
    timesheet_files = [f for f in timesheet_files if not f.startswith('test_export')]

    print(f"\nFound {len(timesheet_files)} timesheet files:")
    for f in timesheet_files:
        print(f"  - {f}")

    # Extract data
    results = extractor.extract_multiple_timesheets(timesheet_files)

    print(f"\n--- Extraction Results ---")
    print(f"Successfully extracted: {len(results['data'])} timesheets")
    print(f"Errors: {len(results['errors'])}")

    if results['errors']:
        print("\n--- Errors ---")
        for error in results['errors']:
            print(f"  File: {error['file']}")
            print(f"  Error: {error['error']}")

    if not results['data']:
        print("\nERROR: No data extracted!")
        return

    # Define sort order
    name_order = [
        "Daniel Trif",
        "Jerry Jeremias",
        "Paul Robertson",
        "Zachary Ebbinghaus",
        "Florin Moldovan",
        "Jarrett Zorzi",
        "Yousof Saleh"
    ]

    # Sort data
    sorted_data = extractor.sort_by_name_order(results['data'], name_order)

    print(f"\n--- Sorted Data (by name order) ---")
    for entry in sorted_data:
        print(f"\nName: {entry['name']}")
        print(f"End Date: {entry['end_date'].strftime('%m/%d/%Y')}")
        print(f"Hours: {entry['hours']}")

    # Create CSV export
    print(f"\n--- Creating CSV Export ---")

    end_date = sorted_data[0]['end_date']
    ending_date_formatted = end_date.strftime('%m/%d/%Y')
    ending_date_filename = end_date.strftime('%Y%m%d')

    csv_data = []
    for entry in sorted_data:
        hours = entry['hours']
        csv_data.append({
            'Ending': ending_date_formatted,
            'Employee': entry['name'],
            'Label': 'Hours',
            'Hours_1': hours['Regular Hours'],
            'Hours_2': hours['Overtime 1 Hours'],
            'Hours_3': hours['Overtime 2 Hours'],
            'Hours_4': hours['Drive Hours'],
            'Hours_5': hours['Sick/PEL'],
            'Hours_6': hours['Vacation'],
            'Hours_7': hours['Holiday'],
            'Hours_8': hours['Non-Billable']
        })

    df = pd.DataFrame(csv_data)
    output_file = f"timesheet_export_{ending_date_filename}.csv"
    df.to_csv(output_file, index=False)

    print(f"CSV exported to: {output_file}")
    print(f"\n--- CSV Preview ---")
    print(df.to_string(index=False))

    print(f"\n--- Comparing with example_ts.csv ---")
    try:
        example_df = pd.read_csv("example_ts.csv")
        print("Example CSV columns:", example_df.columns.tolist())
        print("Export CSV columns:", df.columns.tolist())
        print("Columns match:", df.columns.tolist() == example_df.columns.tolist())

        print("\nExample name order:")
        for name in example_df['Employee']:
            print(f"  - {name}")

        print("\nExport name order:")
        for name in df['Employee']:
            print(f"  - {name}")

    except Exception as e:
        print(f"Could not compare with example: {e}")

if __name__ == "__main__":
    test_extraction()
