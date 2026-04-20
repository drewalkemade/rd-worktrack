# Node: Employees

**Canvas ID:** `employees`  
**Color:** Purple  
**Panel:** `EmployeesPanel.jsx`  
**API:** `GET /api/employees`

---

## Purpose

Central employee registry. Every other node that references an employee by name resolves through this table.

---

## What It Does

- Lists all employees with their display name, type (Billable / Internal), and alias configuration
- Allows adding new employees and editing existing aliases
- Employee aliases map between:
  - PDF name (e.g. `TRIF, DANIEL`)
  - Travel PDF name (may differ)
  - Display name (used throughout the app)
  - Sage 50 name (for payroll export)
  - Legacy expense code

---

## Business Rules

- Employee identity is **effective-dated** — employees can move between Internal and Billable over time without rewriting history
- Some employees appear in the Centerline PDF but do **not** submit timesheets to R&D (Atkinson, Wiseman, Renwick). The system must not require a timesheet for every PDF employee.
- New employees must be added here before their PDF data can be imported successfully
- Ambiguous name matches must not be silently discarded — they surface as import warnings

---

## Inputs

None (root node — no incoming edges)

---

## Outputs

- Feeds into → **Timesheets**, **Approved Hours** (Wk 1 & 2)

---

## Status Indicators

- Active employee count
- Warning if any unresolved alias conflicts exist
