/**
 * CorrectPanel — day-level correction workflow.
 *
 * For each employee with a variance, this panel shows:
 *   - Which days are mismatched (approved vs timesheet)
 *   - The generated note text to copy into the corrected XLSX
 *   - A "Mark as Noted" action to track that the correction has been identified
 *
 * For Sunday-missing cases (employee has Sunday on timesheet but Centerline
 * didn't include it in the approved hours), this panel supports the override
 * workflow: confirm with employee → record the override.
 *
 * This node does NOT edit timesheet data directly.
 * Standard corrections require the owner to:
 *   1. Note the correction here
 *   2. Edit the employee XLSX (save as _DrewEdit)
 *   3. Re-import via Timesheets node
 *   4. Re-run verification in Compare
 *
 * Sunday overrides are recorded here and do not require an Excel edit.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { getVerification, getDayComparison, getCorrections, identifyCorrection, applySundayOverride } from '../api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtH(n) {
  if (!n || n === 0) return '—'
  return n.toFixed(2)
}

function generateNote(day) {
  if (!day.approved_hours || day.approved_hours === 0) return null
  const hrs = day.approved_hours.toFixed(2)
  if (day.clock_in && day.clock_out) {
    return `Centerline Approved ${hrs}hrs (${day.clock_in}-${day.clock_out})`
  }
  return `Centerline Approved ${hrs}hrs`
}

// ── Copy button ───────────────────────────────────────────────────────────────

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const handle = (e) => {
    e.stopPropagation()
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      className="btn btn-ghost"
      style={{ padding: '1px 7px', fontSize: 10, whiteSpace: 'nowrap' }}
      onClick={handle}
    >
      {copied ? '✓ Copied' : '⎘ Copy'}
    </button>
  )
}

// ── Sunday override form ──────────────────────────────────────────────────────

function SundayOverrideForm({ day, employeeId, periodId, weekNum, onDone }) {
  const [confirmedWith, setConfirmedWith] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const handle = async (e) => {
    e.stopPropagation()
    if (!confirmedWith.trim()) return
    setSaving(true)
    setError(null)
    try {
      await applySundayOverride(periodId, weekNum, {
        employee_id:           employeeId,
        work_date:             day.date,
        timesheet_total_hours: day.timesheet_total,
        difference:            day.difference,
        generated_note:        `Sunday confirmed with ${confirmedWith.trim()} — timesheet override`,
        confirmed_with:        confirmedWith.trim(),
      })
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ marginTop: 6 }} onClick={e => e.stopPropagation()}>
      <div style={{ fontSize: 10, color: '#f59e0b', marginBottom: 4 }}>
        ⚠ Sunday missing from approved hours. Confirm directly with the employee before overriding.
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input
          value={confirmedWith}
          onChange={e => setConfirmedWith(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handle(e) }}
          placeholder="Confirmed with (employee name)…"
          style={{
            flex: 1, background: '#0d1117', border: '1px solid #374151',
            color: '#e2e8f0', borderRadius: 4, padding: '3px 7px', fontSize: 10,
          }}
        />
        <button
          className="btn btn-primary"
          style={{ padding: '3px 10px', fontSize: 10, whiteSpace: 'nowrap' }}
          disabled={saving || !confirmedWith.trim()}
          onClick={handle}
        >
          {saving ? '…' : 'Apply Override'}
        </button>
      </div>
      {error && <div className="msg error" style={{ marginTop: 4, fontSize: 10 }}>✗ {error}</div>}
    </div>
  )
}

// ── Single mismatched day row ─────────────────────────────────────────────────

function MismatchDay({ day, employeeId, employee, correctionMap, periodId, weekNum, onRefresh }) {
  const corrKey = `${employeeId}:${day.date}`
  const existing = correctionMap[corrKey]
  const note = generateNote(day)
  const [saving, setSaving] = useState(false)

  const handleIdentify = async (e) => {
    e.stopPropagation()
    setSaving(true)
    try {
      await identifyCorrection(periodId, weekNum, {
        employee_id:           employeeId,
        work_date:             day.date,
        approved_total_hours:  day.approved_hours,
        timesheet_total_hours: day.timesheet_total,
        difference:            day.difference,
        clock_in:              day.clock_in,
        clock_out:             day.clock_out,
        generated_note:        note,
      })
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  const isSunMissing = day.is_sunday_missing_from_approved
  const bg = isSunMissing ? 'rgba(245,158,11,0.07)' : 'rgba(239,68,68,0.07)'
  const statusColor = existing?.status === 'confirmed' ? '#22c55e'
                    : existing?.status === 'identified' ? '#a78bfa'
                    : null

  return (
    <div style={{
      background: bg,
      border: '1px solid rgba(255,255,255,0.05)',
      borderRadius: 6,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      {/* Day header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <span style={{
          fontWeight: 700, fontSize: 12,
          color: day.is_sunday ? '#a78bfa' : '#e2e8f0',
          minWidth: 80,
        }}>
          {day.day_name} {day.date.slice(5)}
        </span>

        {/* Approved */}
        <span style={{ fontSize: 11, color: '#58a6ff', minWidth: 120 }}>
          {day.in_approved
            ? <>
                {day.clock_in && day.clock_out
                  ? <span style={{ color: '#4b5563' }}>{day.clock_in}→{day.clock_out} </span>
                  : null}
                {fmtH(day.approved_hours)}h
              </>
            : <span style={{ color: '#374151' }}>— not in approved</span>
          }
        </span>

        {/* Timesheet */}
        <span style={{ fontSize: 11, color: '#22c55e', minWidth: 70 }}>
          TS: {day.in_timesheet ? `${fmtH(day.timesheet_total)}h` : '—'}
        </span>

        {/* Delta */}
        {!isSunMissing && (
          <span style={{
            fontSize: 11, fontWeight: 700, minWidth: 60,
            color: day.difference > 0 ? '#ef4444' : '#f59e0b',
          }}>
            Δ {day.difference > 0 ? `−${day.difference.toFixed(2)}` : `+${Math.abs(day.difference).toFixed(2)}`}h
          </span>
        )}

        {/* Status */}
        {statusColor && (
          <span style={{ fontSize: 10, color: statusColor, marginLeft: 'auto' }}>
            {existing.status === 'confirmed' ? '✓ override confirmed' : '✓ noted'}
          </span>
        )}
      </div>

      {/* Standard correction: note text */}
      {!isSunMissing && note && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            flex: 1, fontFamily: 'monospace', fontSize: 11,
            color: '#a78bfa', background: '#0d1117',
            padding: '4px 8px', borderRadius: 4,
            border: '1px solid #21262d',
          }}>
            {note}
          </span>
          <CopyButton text={note} />
          {!existing && (
            <button
              className="btn btn-ghost"
              style={{ padding: '2px 8px', fontSize: 10, whiteSpace: 'nowrap' }}
              disabled={saving}
              onClick={handleIdentify}
            >
              {saving ? '…' : '✓ Mark Noted'}
            </button>
          )}
        </div>
      )}

      {/* Instructions for standard correction */}
      {!isSunMissing && (
        <div style={{ fontSize: 10, color: '#4b5563', marginTop: 6, lineHeight: 1.5 }}>
          Copy the note above → edit the employee's XLSX for {day.day_name} {day.date.slice(5)} → save as <em>_DrewEdit.xlsx</em> → re-import via Timesheets node → re-run verification in Compare.
        </div>
      )}

      {/* Sunday override */}
      {isSunMissing && !existing && (
        <SundayOverrideForm
          day={day}
          employeeId={employeeId}
          periodId={periodId}
          weekNum={weekNum}
          onDone={onRefresh}
        />
      )}
      {isSunMissing && existing?.status === 'confirmed' && (
        <div style={{ fontSize: 11, color: '#22c55e', marginTop: 4 }}>
          ✓ Override confirmed with <strong>{existing.confirmed_with}</strong>
        </div>
      )}
    </div>
  )
}

// ── Employee correction section ───────────────────────────────────────────────

function EmployeeSection({ verRow, dayEmp, correctionMap, periodId, weekNum, onRefresh }) {
  const [expanded, setExpanded] = useState(true)

  const mismatchedDays = (dayEmp?.days || []).filter(
    d => Math.abs(d.difference) >= 0.01 || d.is_sunday_missing_from_approved
  )

  if (!mismatchedDays.length) return null

  const allNoted = mismatchedDays.every(d => {
    const key = `${verRow.employee_id}:${d.date}`
    return correctionMap[key]
  })

  return (
    <div style={{
      marginBottom: 16,
      border: '1px solid #21262d',
      borderRadius: 8,
      overflow: 'hidden',
    }}>
      {/* Employee header */}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '8px 14px', background: '#161b22',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(e => !e)}
      >
        <span style={{ fontSize: 11, color: '#4b5563' }}>{expanded ? '▾' : '▸'}</span>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#e2e8f0', flex: 1 }}>
          {verRow.display_name}
        </span>
        <span style={{ fontSize: 11, color: '#ef4444' }}>
          {mismatchedDays.length} mismatch{mismatchedDays.length !== 1 ? 'es' : ''}
        </span>
        {allNoted && (
          <span style={{ fontSize: 10, color: '#a78bfa' }}>✓ all noted</span>
        )}
      </div>

      {expanded && (
        <div style={{ padding: '10px 14px' }}>
          {mismatchedDays.map(d => (
            <MismatchDay
              key={d.date}
              day={d}
              employeeId={verRow.employee_id}
              employee={verRow.display_name}
              correctionMap={correctionMap}
              periodId={periodId}
              weekNum={weekNum}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function CorrectPanel({ periodId, weekNum, onClose, onDone }) {
  const [verification,  setVerification]  = useState(null)
  const [dayData,       setDayData]       = useState(null)
  const [corrections,   setCorrections]   = useState([])

  const loadAll = useCallback(async () => {
    const [v, d, c] = await Promise.allSettled([
      getVerification(periodId, weekNum),
      getDayComparison(periodId, weekNum),
      getCorrections(periodId, weekNum),
    ])
    if (v.status === 'fulfilled') setVerification(v.value)
    if (d.status === 'fulfilled') setDayData(d.value)
    if (c.status === 'fulfilled') setCorrections(c.value.corrections || [])
  }, [periodId, weekNum])

  useEffect(() => {
    if (periodId) loadAll()
  }, [periodId, weekNum])

  // Build lookup maps
  const dayMap = {}
  if (dayData?.employees) {
    for (const emp of dayData.employees) dayMap[emp.display_name] = emp
  }

  // correctionMap keyed by "employeeId:date"
  const correctionMap = {}
  for (const c of corrections) {
    // We need employee_id — join via verification rows
    const verRow = (verification?.rows || []).find(r => r.display_name === c.display_name)
    if (verRow) correctionMap[`${verRow.employee_id}:${c.work_date}`] = c
  }

  // Employees needing correction
  const needsCorrection = (verification?.rows || []).filter(r => r.status === 'needs_review')

  const allAddressed = needsCorrection.length > 0 && needsCorrection.every(r => {
    const emp = dayMap[r.display_name]
    if (!emp) return false
    return emp.days
      .filter(d => Math.abs(d.difference) >= 0.01 || d.is_sunday_missing_from_approved)
      .every(d => correctionMap[`${r.employee_id}:${d.date}`])
  })

  return (
    <>
      <div className="panel-header">
        <h2>✏️ Week {weekNum} — Correct</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 14, lineHeight: 1.6 }}>
          Day-level corrections for employees whose approved hours don't match their timesheet.
          Copy the note text for each mismatch → edit the employee's XLSX → re-import.
          Sunday-missing cases can be confirmed and overridden here without an Excel edit.
        </div>

        {!needsCorrection.length && (
          <div style={{ fontSize: 12, color: '#22c55e' }}>
            ✓ No employees need correction this week.
            {!verification && (
              <span style={{ color: '#8b949e' }}> Run verification in Compare first.</span>
            )}
          </div>
        )}

        {allAddressed && (
          <div className="msg success" style={{ marginBottom: 12, fontSize: 11 }}>
            ✓ All mismatches noted. Re-import corrected timesheets via the Timesheets node,
            then re-run verification in Compare to confirm the variances cleared.
          </div>
        )}

        {needsCorrection.map(r => (
          <EmployeeSection
            key={r.employee_id}
            verRow={r}
            dayEmp={dayMap[r.display_name]}
            correctionMap={correctionMap}
            periodId={periodId}
            weekNum={weekNum}
            onRefresh={loadAll}
          />
        ))}

        {needsCorrection.length > 0 && (
          <div style={{
            marginTop: 8, padding: '8px 12px',
            background: '#0d1117', borderRadius: 6,
            border: '1px solid #21262d', fontSize: 11, color: '#4b5563',
            lineHeight: 1.6,
          }}>
            <strong style={{ color: '#8b949e' }}>Workflow:</strong> Note each mismatch →
            edit the XLSX and save as <em>_DrewEdit.xlsx</em> →
            re-import via <strong style={{ color: '#8b949e' }}>Timesheets</strong> node →
            re-run verification in <strong style={{ color: '#8b949e' }}>Compare</strong> →
            once clear, verify the employee in Compare.
          </div>
        )}

      </div>
    </>
  )
}
