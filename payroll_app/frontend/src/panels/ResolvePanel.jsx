/**
 * ResolvePanel — per-day source adjudication.
 *
 * For each employee with a variance, the owner picks which source is
 * authoritative for each mismatched day:
 *
 *   "Approved is correct"  → CL hours win; DrewEdit export will rewrite
 *                            that cell and add the generated note.
 *   "Timesheet is correct" → Employee hours stand; no XLSX change needed.
 *                            For Sunday-missing cases, requires confirming
 *                            with the employee (name recorded).
 *
 * Decisions are persisted to correction_log. Nothing is written to XLSX
 * here — that happens downstream in the DrewEdit export node.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { getVerification, getDayComparison, getCorrections, resolveCorrection } from '../api'
import { downloadCsv } from '../utils/csv'

function fmtH(n) {
  if (n == null || n === 0) return '—'
  return Number(n).toFixed(2)
}

// ── Sunday-missing "Timesheet is correct" confirmation form ──────────────────

function SundayConfirmForm({ onConfirm, saving }) {
  const [name, setName] = useState('')
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8 }}>
      <input
        value={name}
        onChange={e => setName(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && name.trim()) onConfirm(name.trim()) }}
        placeholder="Confirmed with (employee name)…"
        autoFocus
        style={{
          flex: 1, background: '#0d1117', border: '1px solid #374151',
          color: '#e2e8f0', borderRadius: 4, padding: '4px 8px', fontSize: 11,
        }}
      />
      <button
        className="btn btn-primary"
        style={{ padding: '4px 12px', fontSize: 11, whiteSpace: 'nowrap' }}
        disabled={saving || !name.trim()}
        onClick={() => onConfirm(name.trim())}
      >
        {saving ? '…' : 'Confirm'}
      </button>
    </div>
  )
}

// ── Single mismatched day card ────────────────────────────────────────────────

function MismatchDay({ day, employeeId, periodId, weekNum, resolution, onRefresh }) {
  const [saving,         setSaving]         = useState(false)
  const [error,          setError]          = useState(null)
  const [sundayPending,  setSundayPending]  = useState(false) // waiting for confirmed_with

  const isSunMissing = day.is_sunday_missing_from_approved
  const resolved     = resolution?.status === 'resolved'

  const submit = async (source, confirmedWith = null) => {
    setSaving(true)
    setError(null)
    try {
      await resolveCorrection(periodId, weekNum, {
        employee_id:           employeeId,
        work_date:             day.date,
        source,
        approved_total_hours:  day.approved_hours,
        timesheet_total_hours: day.timesheet_total,
        difference:            day.difference,
        clock_in:              day.clock_in,
        clock_out:             day.clock_out,
        is_sunday_missing:     isSunMissing,
        confirmed_with:        confirmedWith,
      })
      setSundayPending(false)
      onRefresh()
    } catch (err) {
      const detail = err.response?.data?.detail || err.response?.data || err.message
      setError(typeof detail === 'object' ? JSON.stringify(detail) : String(detail))
    } finally {
      setSaving(false)
    }
  }

  const handleApproved   = () => submit('approved_wins')
  const handleTimesheet  = () => {
    if (isSunMissing) {
      setSundayPending(true)
    } else {
      submit('timesheet_wins')
    }
  }
  const handleSundayConfirm = (name) => submit('timesheet_wins', name)

  const bg = isSunMissing ? 'rgba(245,158,11,0.06)' : 'rgba(239,68,68,0.06)'

  return (
    <div style={{
      background: resolved ? 'rgba(34,197,94,0.04)' : bg,
      border: `1px solid ${resolved ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.05)'}`,
      borderRadius: 6,
      padding: '10px 14px',
      marginBottom: 8,
    }}>
      {/* Day header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{
          fontWeight: 700, fontSize: 12,
          color: isSunMissing ? '#f59e0b' : (day.is_sunday ? '#a78bfa' : '#e2e8f0'),
          minWidth: 100,
        }}>
          {day.day_name} {day.date?.slice(5)}
          {isSunMissing && <span style={{ fontSize: 10, marginLeft: 6, color: '#f59e0b' }}>⚠ Sunday missing</span>}
        </span>

        {/* Approved — show travel breakdown when travel was subtracted from PDF total */}
        <span style={{ fontSize: 11, color: '#58a6ff', minWidth: 150 }}>
          {day.in_approved
            ? <>
                {day.clock_in && day.clock_out
                  ? <span style={{ color: '#4b5563' }}>{day.clock_in}→{day.clock_out} </span>
                  : null}
                <strong>{fmtH(day.approved_hours)}h</strong>
                {day.approved_travel_day > 0 && (
                  <span style={{ fontSize: 10, color: '#6b7280', marginLeft: 4 }}>
                    ({fmtH(day.approved_total)}h PDF − {fmtH(day.approved_travel_day)} travel)
                  </span>
                )}
              </>
            : <span style={{ color: '#374151' }}>— not in approved</span>
          }
        </span>

        {/* Timesheet — labor hours only (reg + OT; drive is in the approved travel bucket) */}
        <span style={{ fontSize: 11, color: '#22c55e', minWidth: 80 }}>
          TS: <strong>{day.in_timesheet ? `${fmtH(day.timesheet_total)}h` : '—'}</strong>
          {day.in_timesheet && day.timesheet_drive > 0 && (
            <span style={{ fontSize: 10, color: '#6b7280', marginLeft: 4 }}>
              + {fmtH(day.timesheet_drive)} drive
            </span>
          )}
        </span>

        {/* Delta */}
        {!isSunMissing && (
          <span style={{
            fontSize: 11, fontWeight: 700, minWidth: 70,
            color: day.difference > 0 ? '#ef4444' : '#f59e0b',
          }}>
            Δ {day.difference > 0
              ? `−${day.difference.toFixed(2)}`
              : `+${Math.abs(day.difference).toFixed(2)}`}h
          </span>
        )}

        {/* Resolved badge */}
        {resolved && (
          <span style={{
            marginLeft: 'auto', fontSize: 10, fontWeight: 600,
            color: resolution.correction_type === 'approved_wins' ? '#58a6ff' : '#22c55e',
          }}>
            {resolution.correction_type === 'approved_wins'
              ? '✓ Approved used'
              : resolution.confirmed_with
                ? `✓ Timesheet used — confirmed with ${resolution.confirmed_with}`
                : '✓ Timesheet used'}
          </span>
        )}
      </div>

      {/* Note preview when resolved */}
      {resolved && resolution.generated_note && (
        <div style={{
          marginTop: 6, fontFamily: 'monospace', fontSize: 10,
          color: '#6b7280', background: '#0d1117',
          padding: '3px 8px', borderRadius: 4,
          border: '1px solid #21262d', display: 'inline-block',
        }}>
          {resolution.generated_note}
        </div>
      )}

      {/* Action buttons — only when not yet resolved */}
      {!resolved && !sundayPending && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          {day.in_approved && (
            <button
              className="btn btn-ghost"
              style={{
                padding: '5px 14px', fontSize: 11,
                borderColor: '#1d4ed8', color: '#93c5fd',
              }}
              disabled={saving}
              onClick={handleApproved}
            >
              {saving ? '…' : '✓ Approved is correct'}
            </button>
          )}
          <button
            className="btn btn-ghost"
            style={{
              padding: '5px 14px', fontSize: 11,
              borderColor: '#166534', color: '#86efac',
            }}
            disabled={saving}
            onClick={handleTimesheet}
          >
            {saving ? '…' : isSunMissing ? '✓ Timesheet is correct (confirm with employee →)' : '✓ Timesheet is correct'}
          </button>
        </div>
      )}

      {/* Sunday confirmation input */}
      {!resolved && sundayPending && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, color: '#f59e0b', marginBottom: 4 }}>
            Confirm directly with the employee that they worked this Sunday:
          </div>
          <SundayConfirmForm onConfirm={handleSundayConfirm} saving={saving} />
          <button
            onClick={() => setSundayPending(false)}
            style={{
              background: 'none', border: 'none', color: '#4b5563',
              fontSize: 10, cursor: 'pointer', marginTop: 4,
            }}
          >
            cancel
          </button>
        </div>
      )}

      {error && (
        <div className="msg error" style={{ marginTop: 6, fontSize: 10 }}>✗ {error}</div>
      )}
    </div>
  )
}

// ── Employee section ──────────────────────────────────────────────────────────

function EmployeeSection({ verRow, dayEmp, resolutionMap, periodId, weekNum, onRefresh }) {
  const [expanded, setExpanded] = useState(true)

  const mismatchedDays = (dayEmp?.days || []).filter(
    d => Math.abs(d.difference) >= 0.01 || d.is_sunday_missing_from_approved
  )

  if (!mismatchedDays.length) return null

  const allResolved = mismatchedDays.every(d => {
    const key = `${verRow.employee_id}:${d.date}`
    return resolutionMap[key]?.status === 'resolved'
  })

  return (
    <div style={{
      marginBottom: 16,
      border: `1px solid ${allResolved ? '#166534' : '#21262d'}`,
      borderRadius: 8,
      overflow: 'hidden',
    }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '8px 14px',
          background: allResolved ? 'rgba(34,197,94,0.06)' : '#161b22',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(e => !e)}
      >
        <span style={{ fontSize: 11, color: '#4b5563' }}>{expanded ? '▾' : '▸'}</span>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#e2e8f0', flex: 1 }}>
          {verRow.display_name}
        </span>
        <span style={{ fontSize: 11, color: allResolved ? '#22c55e' : '#ef4444' }}>
          {mismatchedDays.length} variance{mismatchedDays.length !== 1 ? 's' : ''}
        </span>
        {allResolved && (
          <span style={{ fontSize: 10, color: '#22c55e' }}>✓ all resolved</span>
        )}
      </div>

      {expanded && (
        <div style={{ padding: '10px 14px' }}>
          {mismatchedDays.map(d => (
            <MismatchDay
              key={d.date}
              day={d}
              employeeId={verRow.employee_id}
              periodId={periodId}
              weekNum={weekNum}
              resolution={resolutionMap[`${verRow.employee_id}:${d.date}`]}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function ResolvePanel({ periodId, weekNum, onClose, onDone }) {
  const [verification, setVerification] = useState(null)
  const [dayData,      setDayData]      = useState(null)
  const [corrections,  setCorrections]  = useState([])

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

  const dayMap = {}
  if (dayData?.employees) {
    for (const emp of dayData.employees) dayMap[emp.display_name] = emp
  }

  // resolutionMap keyed by "employeeId:date"
  const resolutionMap = {}
  for (const c of corrections) {
    const verRow = (verification?.rows || []).find(r => r.display_name === c.display_name)
    if (verRow) resolutionMap[`${verRow.employee_id}:${c.work_date}`] = c
  }

  const needsReview = (verification?.rows || []).filter(r => r.status === 'needs_review')

  const allResolved = needsReview.length > 0 && needsReview.every(r => {
    const emp = dayMap[r.display_name]
    if (!emp) return false
    return emp.days
      .filter(d => Math.abs(d.difference) >= 0.01 || d.is_sunday_missing_from_approved)
      .every(d => resolutionMap[`${r.employee_id}:${d.date}`]?.status === 'resolved')
  })

  return (
    <>
      <div className="panel-header">
        <h2>⚖️ Week {weekNum} — Resolve Mismatches</h2>
        {corrections.length > 0 && (
          <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => {
              const out = [['Employee','Date','Approved Total','Approved Travel','Approved Labor','TS Hours','Diff','Resolution','Confirmed With','Note']]
              for (const c of corrections) {
                out.push([c.display_name,c.work_date,c.approved_total_hours||'',c.approved_travel_day||'',c.approved_total_hours||'',c.timesheet_total_hours||'',c.difference||'',c.correction_type||'',c.confirmed_with||'',c.generated_note||''])
              }
              downloadCsv(out, `debug_resolve_wk${weekNum}.csv`)
            }}>↓ Debug CSV</button>
        )}
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 14, lineHeight: 1.6 }}>
          For each variance, select which source is correct. Decisions are saved to the
          database — the DrewEdit export will apply corrections and write notes automatically.
          Nothing is written to Excel here.
        </div>

        {!verification && (
          <div style={{ fontSize: 12, color: '#4b5563' }}>
            Run verification in Compare first to identify variances.
          </div>
        )}

        {verification && !needsReview.length && (
          <div style={{ fontSize: 12, color: '#22c55e' }}>
            ✓ No variances this week — nothing to resolve.
          </div>
        )}

        {allResolved && (
          <div className="msg success" style={{ marginBottom: 14, fontSize: 11 }}>
            ✓ All variances resolved. Re-run verification in Compare to confirm they cleared,
            then verify each employee.
          </div>
        )}

        {needsReview.map(r => (
          <EmployeeSection
            key={r.employee_id}
            verRow={r}
            dayEmp={dayMap[r.display_name]}
            resolutionMap={resolutionMap}
            periodId={periodId}
            weekNum={weekNum}
            onRefresh={loadAll}
          />
        ))}

        {needsReview.length > 0 && (
          <div style={{
            marginTop: 8, padding: '8px 12px',
            background: '#0d1117', borderRadius: 6,
            border: '1px solid #21262d', fontSize: 11, color: '#4b5563',
            lineHeight: 1.7,
          }}>
            <strong style={{ color: '#8b949e' }}>How it works:</strong> Pick a source for each
            variance → decisions saved here → re-run <strong style={{ color: '#8b949e' }}>Compare</strong> to
            confirm variances cleared → verify employees → DrewEdit export node will generate
            corrected XLSX files with notes already written in.
          </div>
        )}

      </div>
    </>
  )
}
