# Open Issues

These are the remaining product and operational decisions that should be resolved during implementation. They are not blockers to planning, but they will affect workflow behavior, auditability, and user experience.

## Approval Authority

Need explicit rules for which actions require an owner approval step:
- weekly verification complete
- biweekly payroll approval
- expense reimbursement ready
- billing ready

Questions:
- Which steps should require an explicit final approval click?
- Which steps can happen automatically once all prerequisites are satisfied?

## Locking And Reopening Rules

Need explicit behavior for approved or exported records.

Questions:
- After a weekly approval or pay period is approved, can it still be edited?
- If edited after approval, should the period move back to a review-required state?
- Who can reopen an approved week or period?
- What happens if payroll or billing exports already exist and data later changes?

## Backup And Recovery

SQLite will be the system of record, so backup expectations should be defined.

Questions:
- Where should the SQLite file live?
- How should it be backed up?
- Should workbook outputs be versioned or copied before writing?
- How should recovery work if the DB or an output workbook is corrupted?

## Receipt Storage Strategy

Need a concrete rule for where receipts live and whether they are copied or renamed in place.

Questions:
- Should receipts remain in their original location and only be indexed?
- Should the app copy them into a managed folder structure?
- Should receipt normalization rename in place, or create a normalized copy?
- What folder structure is preferred for long-term retrieval?

## Billing Readiness Rules

Need a formal definition of when a week is ready to bill.

Questions:
- Must all weekly employee verifications be complete?
- Must all non-per-diem receipts be present?
- Must provisional Sunday travel be resolved first?
- Are there any cases where partial billing is allowed?

## Reimbursement Readiness Rules

Need a formal definition of when employee expenses are ready for reimbursement.

Questions:
- Does one missing receipt block the whole employee-period reimbursement, or only that line item?
- Can per diem still be reimbursed if other expense items for that employee are blocked?
- Should CAD and USD reimbursement readiness be tracked separately?

## Historical Workbook Strategy

Need a decision on whether outputs should write into master files directly or use dated copies.

Questions:
- Should the app append into the operational master workbooks?
- Should it write into dated/generated working copies instead?
- Should a backup copy be made automatically before any workbook write?

## User Model

The current plan reads as a single-owner local workflow, which is likely correct, but it should stay explicit.

Questions:
- Is this strictly a single-user local app?
- Should the design assume future multi-user review/edit workflows?
- If multiple users ever matter, what approval/audit distinctions would be needed?

## Scope Discipline / Release Planning

The feature set is now broad enough that delivery sequencing matters.

Recommended first release focus:
- source-file ingestion
- daily timesheet + expense extraction
- weekly verification
- payroll reconciliation
- receipt tracking
- expense reimbursement summary
- source document access

Later-phase items:
- richer dashboards
- deep profit analytics
- optional lateness/exception reporting
- employee-facing template validation
- receipt image resize/compression polish

Question:
- Do you want an explicit MVP definition written down next?
