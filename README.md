# R&D WorkTrack

R&D WorkTrack is a local Streamlit application for R&D Controls Corp that replaces the current manual payroll, billing verification, and expense reimbursement workflow.

The system is being built to manage:

- weekly customer payroll and travel approval intake
- biweekly employee timesheet intake
- payroll reconciliation and Sage 50 payroll export
- employee expense reimbursement and receipt tracking
- structured weekly verification controls with auditability

## Status

Initial repository scaffold. Project files will be added after the current Phase 2 implementation work is complete in the existing development workspace.

## Planned Stack

- Python
- Streamlit
- SQLite
- pandas
- openpyxl
- pdfplumber
- rapidfuzz
- pytest

## Design Priorities

- accuracy over speed
- explicit business controls
- traceability and auditability
- readable, debug-friendly code
- preservation of source documents and manual review context
