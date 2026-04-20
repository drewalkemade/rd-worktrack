/**
 * ComparePanel — Week N comparison: approved hours vs employee timesheet.
 *
 * Purpose: surface who has mismatches and exactly which day is different.
 * This node identifies problems — it does not apply corrections.
 * Corrections happen in the Correct node (requires reclassifier.py).
 *
 * Two levels of detail:
 *   1. Weekly summary row per employee — approved totals vs timesheet totals + variance
 *   2. Expandable day rows — per-day approved (clock-in/out) vs timesheet hours + Δ
 *
 * Sunday-missing exception is flagged here when Sunday exists in the timesheet
 * but is absent from approved hours entirely.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { runVerification, getVerification, getDayComparison, setVerified } from '../api'
import { downloadCsv } from '../utils/csv'

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtH(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return n.toFixed(1)
}

function DeltaCell({ v }) {
  if (v === null || v === undefined || Math.abs(v) < 0.01)
    return <span className="zero">—</span>
  // diff = approved - timesheet
  // positive = timesheet is UNDER approved (timesheet needs to go up)
  // negative = timesheet is OVER approved (timesheet needs to come down)
  const color = v > 0 ? '#ef4444' : '#f59e0b'
  const label = v > 0 ? `−${v.toFixed(2)}` : `+${Math.abs(v).toFixed(2)}`
  const title = v > 0
    ? `Timesheet is ${v.toFixed(2)}h below approved`
    : `Timesheet is ${Math.abs(v).toFixed(2)}h above approved`
  return <span style={{ color, fontWeight: 700 }} title={title}>{label}</span>
}

// Variance at the weekly level: approved vs timesheet totals
function WeeklyVariance({ v }) {
  if (!v || Math.abs(v) < 0.01) return <span className="zero">—</span>
  const color = Math.abs(v) >= 0.5 ? '#ef4444' : '#f59e0b'
  return (
    <span style={{ color, fontWeight: 700 }}>
      {v > 0 ? '+' : ''}{v.toFixed(1)}
    </span>
  )
}

// ── Status and constants ──────────────────────────────────────────────────────

const STATUS_STYLE = {
  verified:     { background: '#166534', color: '#fff' },
  needs_review: { background: '#7c2d12', color: '#fff' },
  pending:      { background: '#1f2937', color: '#6b7280' },
}

const SUN_LABELS = {
  confirmed:              'confirmed',
  pending_next_pdf:       'pending PDF',
  assumed_from_timesheet: 'assumed TS',
  'n/a':                  'n/a',
}

const SUN_COLOR = {
  pending_next_pdf:       '#f59e0b',
  assumed_from_timesheet: '#a78bfa',
  confirmed:              '#22c55e',
}

// ── Day detail rows (shown when employee is expanded) ─────────────────────────

function DayDetailRows({ days, colSpan }) {
  if (!days || !days.length) {
    return (
      <tr>
        <td colSpan={colSpan} style={{ padding: '6px 24px', fontSize: 11, color: '#4b5563', background: '#0d1117' }}>
          No daily detail available — import the payroll PDF to see clock-in/out rows.
        </td>
      </tr>
    )
  }

  return days.map(d => {
    const hasMismatch = Math.abs(d.difference) >= 0.01
    const isSunMissing = d.is_sunday_missing_from_approved
    const bg = isSunMissing    ? 'rgba(245,158,11,0.08)'
             : hasMismatch     ? 'rgba(239,68,68,0.07)'
             : 'rgba(255,255,255,0.02)'

    return (
      <tr key={d.date} style={{ background: bg }}>
        <td colSpan={colSpan} style={{ padding: 0 }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '110px 1fr 1fr 70px 1fr',
            gap: '0 12px',
            padding: '4px 24px 4px 36px',
            fontSize: 11,
            alignItems: 'center',
          }}>
            {/* Day + date */}
            <div style={{ color: d.is_sunday ? '#a78bfa' : '#8b949e', fontWeight: d.is_sunday ? 600 : 400 }}>
              {d.day_name}&nbsp;
              <span style={{ color: '#4b5563' }}>{d.date.slice(5)}</span>
              {d.is_dbl_day && (
                <span style={{ marginLeft: 5, fontSize: 9, color: '#f59e0b', fontWeight: 700 }}>DBL</span>
              )}
            </div>

            {/* Approved */}
            <div>
              {d.in_approved ? (
                <span style={{ color: '#58a6ff' }}>
                  {d.clock_in && d.clock_out
                    ? <><span style={{ color: '#4b5563' }}>{d.clock_in}→{d.clock_out}</span> {d.approved_hours.toFixed(2)}h</>
                    : <>{d.approved_hours.toFixed(2)}h</>
                  }
                </span>
              ) : (
                <span style={{ color: '#374151' }}>— no approved entry</span>
              )}
            </div>

            {/* Timesheet */}
            <div>
              {d.in_timesheet && d.timesheet_total > 0 ? (
                <span style={{ color: '#22c55e' }}>{d.timesheet_total.toFixed(2)}h</span>
              ) : (
                <span style={{ color: '#374151' }}>—</span>
              )}
            </div>

            {/* Delta */}
            <div style={{ textAlign: 'right' }}>
              <DeltaCell v={d.difference} />
            </div>

            {/* Flags */}
            <div>
              {isSunMissing && (
                <span style={{ color: '#f59e0b', fontSize: 10 }}>
                  ⚠ Sunday missing from approved
                </span>
              )}
              {hasMismatch && !isSunMissing && (
                <span style={{ color: '#ef4444', fontSize: 10 }}>
                  mismatch
                </span>
              )}
            </div>
          </div>
        </td>
      </tr>
    )
  })
}

// ── Verify action ─────────────────────────────────────────────────────────────

function VerifyAction({ row, periodId, weekNum, onVerified }) {
  const [saving, setSaving] = useState(false)

  if (row.status === 'verified') return null

  // Employees with variance must go through the Correct node first
  if (row.status === 'needs_review') {
    return (
      <span style={{ fontSize: 10, color: '#f59e0b', whiteSpace: 'nowrap' }}>
        → Correct node
      </span>
    )
  }

  const handleVerify = async (e) => {
    e.stopPropagation()
    setSaving(true)
    try {
      await setVerified(periodId, weekNum, row.employee_id, null)
      onVerified()
    } finally {
      setSaving(false)
    }
  }

  return (
    <button
      className="btn btn-ghost"
      style={{ padding: '2px 8px', fontSize: 10, whiteSpace: 'nowrap' }}
      disabled={saving}
      onClick={handleVerify}
    >
      {saving ? '…' : '✓ Verify'}
    </button>
  )
}

// ── Comparison table ──────────────────────────────────────────────────────────

const COL_SPAN = 16   // total columns in the table

function ComparisonTable({ rows, dayMap, expanded, onToggle, periodId, weekNum, onVerified }) {
  if (!rows || !rows.length) {
    return (
      <div style={{ color: '#8b949e', fontSize: 12, marginTop: 8 }}>
        Run verification to see the comparison.
      </div>
    )
  }

  const hasSunCol = rows.some(r => r.travel_sun_status && r.travel_sun_status !== 'n/a')

  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table className="output-table" style={{ fontSize: 11, tableLayout: 'auto' }}>
        <thead>
          <tr>
            <th rowSpan={2} style={{ verticalAlign: 'bottom', width: 16 }}></th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Employee</th>
            <th colSpan={4} className="col-approved col-group-start"
              style={{ textAlign: 'center', borderBottom: '1px solid #374151', paddingBottom: 2 }}>
              Approved
            </th>
            <th colSpan={4} className="col-timesheet col-group-start"
              style={{ textAlign: 'center', borderBottom: '1px solid #374151', paddingBottom: 2 }}>
              Timesheet
            </th>
            <th colSpan={3} className="col-variance col-group-start"
              style={{ textAlign: 'center', borderBottom: '1px solid #374151', paddingBottom: 2 }}>
              Variance
            </th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>PD</th>
            {hasSunCol && <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Sun</th>}
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Status</th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}></th>
          </tr>
          <tr>
            <th className="col-approved col-group-start">REG</th>
            <th className="col-approved">OT</th>
            <th className="col-approved">DBL</th>
            <th className="col-approved" style={{ fontStyle: 'italic', color: '#a78bfa' }}>Trvl</th>
            <th className="col-timesheet col-group-start">REG</th>
            <th className="col-timesheet">OT1</th>
            <th className="col-timesheet">OT2</th>
            <th className="col-timesheet">Drv</th>
            <th className="col-variance col-group-start">ΔREG</th>
            <th className="col-variance">ΔOT</th>
            <th className="col-variance">ΔDBL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const isExpanded = expanded.has(r.display_name)
            const empDays = dayMap[r.display_name]
            const hasDays = empDays && empDays.days?.length > 0
            const rowBg = r.status === 'needs_review' ? 'rgba(124,45,18,0.18)'
                        : r.status === 'verified'      ? 'rgba(22,101,52,0.1)'
                        : 'transparent'
            return (
              <React.Fragment key={r.employee_id}>
                <tr
                  key={r.employee_id}
                  style={{ background: rowBg, cursor: 'pointer' }}
                  onClick={() => onToggle(r.display_name)}
                >
                  {/* Expand toggle */}
                  <td style={{ color: '#4b5563', fontSize: 10, paddingRight: 0, width: 16 }}>
                    {isExpanded ? '▾' : '▸'}
                  </td>

                  {/* Employee name */}
                  <td style={{ fontWeight: 600 }}>
                    {r.display_name}
                    {r.needs_expense_review && (
                      <span title="Expense review needed"
                        style={{ marginLeft: 5, color: '#f59e0b', fontSize: 10 }}>💰</span>
                    )}
                    {empDays?.has_mismatch && (
                      <span style={{ marginLeft: 5, fontSize: 9, color: '#ef4444' }}>
                        {empDays.mismatch_count} day{empDays.mismatch_count !== 1 ? 's' : ''}
                      </span>
                    )}
                    {r.extra_expense_note && (
                      <div style={{ fontSize: 10, color: '#8b949e', fontWeight: 400, marginTop: 1 }}>
                        📝 {r.extra_expense_note}
                      </div>
                    )}
                  </td>

                  {/* Approved */}
                  <td className="col-approved col-group-start">{fmtH(r.approved_reg)}</td>
                  <td className="col-approved">{fmtH(r.approved_ot)}</td>
                  <td className="col-approved">{fmtH(r.approved_dbl)}</td>
                  <td className="col-approved" style={{ fontStyle: 'italic', color: '#a78bfa' }}>
                    {fmtH(r.approved_travel)}
                  </td>

                  {/* Timesheet */}
                  <td className="col-timesheet col-group-start">{fmtH(r.timesheet_reg)}</td>
                  <td className="col-timesheet">{fmtH(r.timesheet_ot1)}</td>
                  <td className="col-timesheet">{fmtH(r.timesheet_ot2)}</td>
                  <td className="col-timesheet">{fmtH(r.timesheet_drive)}</td>

                  {/* Variance */}
                  <td className="col-variance col-group-start">
                    <WeeklyVariance v={r.reg_variance} />
                  </td>
                  <td className="col-variance"><WeeklyVariance v={r.ot_variance} /></td>
                  <td className="col-variance"><WeeklyVariance v={r.dbl_variance} /></td>

                  {/* Per diem */}
                  <td style={{ color: '#8b949e' }}>
                    {r.per_diem_count > 0 ? r.per_diem_count : <span className="zero">—</span>}
                  </td>

                  {/* Sun status */}
                  {hasSunCol && (
                    <td style={{
                      fontSize: 10,
                      color: SUN_COLOR[r.travel_sun_status] || '#8b949e',
                    }}>
                      {SUN_LABELS[r.travel_sun_status] || r.travel_sun_status || '—'}
                    </td>
                  )}

                  {/* Status badge */}
                  <td>
                    <span style={{
                      ...(STATUS_STYLE[r.status] || STATUS_STYLE.pending),
                      fontSize: 10, padding: '2px 6px', borderRadius: 3, whiteSpace: 'nowrap',
                    }}>
                      {r.status?.replace('_', ' ') || 'pending'}
                    </span>
                  </td>

                  {/* Verify action */}
                  <td style={{ minWidth: 80 }}>
                    <VerifyAction
                      row={r}
                      periodId={periodId}
                      weekNum={weekNum}
                      onVerified={onVerified}
                    />
                  </td>
                </tr>

                {/* Day detail rows */}
                {isExpanded && (
                  <DayDetailRows
                    days={hasDays ? empDays.days : null}
                    colSpan={hasSunCol ? COL_SPAN : COL_SPAN - 1}
                  />
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 10, color: '#4b5563' }}>
        <span><span style={{ color: '#ef4444', fontWeight: 700 }}>−</span> timesheet below approved</span>
        <span><span style={{ color: '#f59e0b', fontWeight: 700 }}>+</span> timesheet above approved</span>
        <span><span style={{ color: '#f59e0b' }}>⚠</span> Sunday missing from approved</span>
        <span style={{ fontStyle: 'italic', color: '#a78bfa' }}>Trvl</span><span>= travel PDF, not in labor total</span>
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function ComparePanel({ periodId, weekNum, onClose, onDone }) {
  const [verifying,     setVerifying]     = useState(false)
  const [verifySummary, setVerifySummary] = useState(null)
  const [verification,  setVerification]  = useState(null)
  const [dayData,       setDayData]       = useState(null)
  const [expanded,      setExpanded]      = useState(new Set())

  const loadData = useCallback(async () => {
    const [v, d] = await Promise.allSettled([
      getVerification(periodId, weekNum),
      getDayComparison(periodId, weekNum),
    ])
    if (v.status === 'fulfilled') setVerification(v.value)
    if (d.status === 'fulfilled') setDayData(d.value)
  }, [periodId, weekNum])

  useEffect(() => {
    if (periodId) loadData()
  }, [periodId, weekNum])

  const handleRunVerification = async () => {
    setVerifying(true)
    setVerifySummary(null)
    try {
      const summary = await runVerification(periodId, weekNum)
      setVerifySummary(summary)
      await loadData()
      onDone?.()
    } catch (err) {
      setVerifySummary({ error: err.response?.data?.detail || err.message })
    } finally {
      setVerifying(false)
    }
  }

  const toggleExpand = useCallback((name) => {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }, [])

  // Build day lookup map: {display_name: {has_mismatch, mismatch_count, days[]}}
  const dayMap = {}
  if (dayData?.employees) {
    for (const emp of dayData.employees) dayMap[emp.display_name] = emp
  }

  const rows       = verification?.rows || []
  const hasRows    = rows.length > 0
  const allVerified  = hasRows && rows.every(r => r.status === 'verified')
  const pendingCount = rows.filter(r => r.status !== 'verified').length
  const mismatchCount = rows.filter(r => r.status === 'needs_review').length

  return (
    <>
      <div className="panel-header">
        <h2>🔍 Week {weekNum} — Compare</h2>
        {dayData && (
          <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => {
              const out = [['Employee','Date','Day','Approved Labor','Approved Total','Travel Day','TS Labor','TS Drive','Diff','Status']]
              for (const emp of dayData.employees || []) {
                const verRow = rows.find(r => r.display_name === emp.display_name)
                for (const d of emp.days || []) {
                  out.push([emp.display_name,d.date,d.day_name,d.approved_hours,d.approved_total,d.approved_travel_day,d.timesheet_total,d.timesheet_drive,d.difference,verRow?.status||''])
                }
              }
              downloadCsv(out, `debug_compare_wk${weekNum}.csv`)
            }}>↓ Debug CSV</button>
        )}
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 12, lineHeight: 1.6 }}>
          Compare Centerline-approved hours against submitted timesheets.
          Click any employee row to expand daily clock-in/out detail and see exactly which day has a mismatch.
          Verify employees whose numbers are correct — take mismatches to the{' '}
          <strong style={{ color: '#e2e8f0' }}>Correct</strong> node.
        </div>

        {/* ── Run / re-run ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary"
            style={{ padding: '5px 14px', fontSize: 12 }}
            onClick={handleRunVerification}
            disabled={verifying}
          >
            {verifying ? '⏳ Running…' : hasRows ? '↺ Re-run Verification' : '▶ Run Verification'}
          </button>

          {allVerified && (
            <span style={{ fontSize: 11, color: '#22c55e' }}>✓ All verified</span>
          )}
          {hasRows && !allVerified && mismatchCount > 0 && (
            <span style={{ fontSize: 11, color: '#ef4444' }}>
              {mismatchCount} mismatch{mismatchCount !== 1 ? 'es' : ''}
            </span>
          )}
          {hasRows && !allVerified && pendingCount > 0 && (
            <span style={{ fontSize: 11, color: '#8b949e' }}>
              {pendingCount} pending
            </span>
          )}
        </div>

        {/* Verification run result */}
        {verifySummary && !verifySummary.error && (
          <div className="msg success" style={{ marginBottom: 8, fontSize: 11 }}>
            ✓ {verifySummary.total_employees} employees —{' '}
            <span style={{ color: '#22c55e' }}>{verifySummary.verified_count} verified</span>
            {verifySummary.needs_review_count > 0 && (
              <span style={{ color: '#ef4444' }}> · {verifySummary.needs_review_count} need review</span>
            )}
            {verifySummary.pending_count > 0 && (
              <span style={{ color: '#8b949e' }}> · {verifySummary.pending_count} pending</span>
            )}
            {verifySummary.provisional_sunday > 0 && (
              <span style={{ color: '#f59e0b' }}> · {verifySummary.provisional_sunday} provisional Sunday</span>
            )}
          </div>
        )}
        {verifySummary?.error && (
          <div className="msg error" style={{ marginBottom: 8 }}>✗ {verifySummary.error}</div>
        )}
        {verifySummary?.warnings?.map((w, i) => (
          <div key={i} className="msg warn" style={{ marginBottom: 4 }}>⚠ {w}</div>
        ))}

        {/* ── Comparison table ── */}
        <ComparisonTable
          rows={rows}
          dayMap={dayMap}
          expanded={expanded}
          onToggle={toggleExpand}
          periodId={periodId}
          weekNum={weekNum}
          onVerified={loadData}
        />

        {/* ── Correct node hint ── */}
        {mismatchCount > 0 && (
          <div style={{
            marginTop: 16, padding: '8px 12px',
            background: '#0d1117', borderRadius: 6,
            border: '1px solid #21262d', fontSize: 11, color: '#4b5563',
          }}>
            {mismatchCount} employee{mismatchCount !== 1 ? 's have' : ' has'} mismatches.
            Open the <strong style={{ color: '#8b949e' }}>Correct</strong> node to apply
            day-level corrections and trigger weekly reclassification.
          </div>
        )}

      </div>
    </>
  )
}
