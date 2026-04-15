/**
 * ApprovedHoursPanel — Week N approved hours workflow.
 *
 * Three sections, in order:
 *   1. Payroll PDF upload  → imports customer_hours via importer.import_payroll_pdf
 *   2. Travel PDF upload   → imports travel_hours   via importer.import_travel_pdf
 *   3. Verification        → run_weekly_verification + per-employee comparison table
 *
 * Used for both Week 1 and Week 2 (weekNum prop = 1 or 2).
 * Also wired to the w{n}_payroll_pdf and w{n}_travel_pdf canvas nodes.
 */
import { useState, useEffect, useRef } from 'react'
import {
  getWeek, importPayrollPdf, importTravelPdf,
  runVerification, getVerification, setVerified,
} from '../api'

// ── small helpers ─────────────────────────────────────────────────────────────

function fmtH(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return n.toFixed(1)
}

function Variance({ v }) {
  if (!v || Math.abs(v) < 0.01) return <span className="zero">—</span>
  const color = v > 0 ? '#f59e0b' : '#ef4444'
  return <span style={{ color, fontWeight: 700 }}>{v > 0 ? '+' : ''}{v.toFixed(1)}</span>
}

const STATUS_STYLE = {
  verified:     { background: '#166534', color: '#fff' },
  needs_review: { background: '#7c2d12', color: '#fff' },
  pending:      { background: '#1f2937', color: '#8b949e' },
}

const SUN_LABELS = {
  confirmed:               'confirmed',
  pending_next_pdf:        'pending PDF',
  assumed_from_timesheet:  'assumed TS',
  'n/a':                   'n/a',
}

// ── PDF drop zone (reusable within this panel) ────────────────────────────────

function PdfDropZone({ label, onFile, file, result, importing }) {
  const [dragOver, setDragOver] = useState(false)
  const ref = useRef()

  const pick = (incoming) => {
    const f = Array.from(incoming).find(f => f.name.toLowerCase().endsWith('.pdf'))
    if (f) onFile(f)
  }

  return (
    <div style={{ marginBottom: 10 }}>
      <div className="section-label" style={{ marginTop: 0 }}>{label}</div>

      {result?.success ? (
        <div className="msg success">
          ✓ {result.filename} — {result.employee_count} employee(s)
          {result.warnings?.map((w, i) => (
            <div key={i} className="msg warn" style={{ marginTop: 4 }}>⚠ {w}</div>
          ))}
        </div>
      ) : (
        <>
          <div
            className={`drop-zone ${dragOver ? 'drag-over' : ''}`}
            style={{ padding: '10px 14px', minHeight: 0 }}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); pick(e.dataTransfer.files) }}
            onClick={() => ref.current?.click()}
          >
            <input ref={ref} type="file" accept=".pdf" style={{ display: 'none' }}
              onChange={e => pick(e.target.files)} />
            {file
              ? <span style={{ color: '#e2e8f0', fontSize: 12 }}>📄 {file.name}</span>
              : <span style={{ fontSize: 12, color: '#4b5563' }}>Drop PDF or click to browse</span>
            }
          </div>
          {result?.error && (
            <div className="msg error" style={{ marginTop: 6 }}>✗ {result.error}</div>
          )}
          {result?.errors?.map((e, i) => (
            <div key={i} className="msg error" style={{ marginTop: 4 }}>✗ {e}</div>
          ))}
        </>
      )}

      {importing && <div style={{ fontSize: 11, color: '#8b949e', marginTop: 6 }}>⏳ Importing…</div>}
    </div>
  )
}

// ── verification table ────────────────────────────────────────────────────────

function VerifyAction({ row, periodId, weekNum, onVerified }) {
  const [expanded, setExpanded] = useState(false)
  const [note,     setNote]     = useState('')
  const [saving,   setSaving]   = useState(false)

  if (row.status === 'verified') return null

  const needsNote = row.status === 'needs_review'

  const handleConfirm = async () => {
    if (needsNote && !note.trim()) return   // note required
    setSaving(true)
    try {
      await setVerified(periodId, weekNum, row.employee_id, note.trim() || null)
      onVerified()
    } finally {
      setSaving(false)
      setExpanded(false)
      setNote('')
    }
  }

  if (!expanded) {
    return (
      <button
        className="btn btn-ghost"
        style={{ padding: '2px 8px', fontSize: 10, whiteSpace: 'nowrap' }}
        onClick={() => needsNote ? setExpanded(true) : handleConfirm()}
      >
        ✓ Verify
      </button>
    )
  }

  // Expanded note input (needs_review only)
  return (
    <div style={{ minWidth: 180 }}>
      <input
        autoFocus
        value={note}
        onChange={e => setNote(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') handleConfirm(); if (e.key === 'Escape') { setExpanded(false); setNote('') } }}
        placeholder="Note required…"
        style={{
          width: '100%', background: '#0d1117', border: '1px solid #374151',
          color: '#e2e8f0', borderRadius: 4, padding: '3px 6px', fontSize: 10,
          marginBottom: 4,
        }}
      />
      <div style={{ display: 'flex', gap: 4 }}>
        <button
          className="btn btn-primary"
          style={{ padding: '2px 8px', fontSize: 10, flex: 1 }}
          disabled={saving || !note.trim()}
          onClick={handleConfirm}
        >
          {saving ? '…' : '✓ Confirm'}
        </button>
        <button
          className="btn btn-ghost"
          style={{ padding: '2px 8px', fontSize: 10 }}
          onClick={() => { setExpanded(false); setNote('') }}
        >
          ✕
        </button>
      </div>
    </div>
  )
}

function VerificationTable({ rows, periodId, weekNum, onVerified }) {
  if (!rows || !rows.length) return (
    <div style={{ color: '#8b949e', fontSize: 12, marginTop: 8 }}>
      No verification data — run verification first.
    </div>
  )

  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table className="output-table" style={{ fontSize: 11 }}>
        <thead>
          <tr>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Employee</th>
            <th colSpan={4} className="col-approved col-group-start" style={{ textAlign: 'center', borderBottom: '1px solid #374151' }}>Approved</th>
            <th colSpan={4} className="col-timesheet col-group-start" style={{ textAlign: 'center', borderBottom: '1px solid #374151' }}>Timesheet</th>
            <th colSpan={3} className="col-variance col-group-start" style={{ textAlign: 'center', borderBottom: '1px solid #374151' }}>Variance</th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>PD</th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Sun</th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Status</th>
            <th rowSpan={2} style={{ verticalAlign: 'bottom' }}></th>
          </tr>
          <tr>
            <th className="col-approved col-group-start">REG</th>
            <th className="col-approved">OT</th>
            <th className="col-approved">DBL</th>
            <th className="col-approved">Trvl</th>
            <th className="col-timesheet col-group-start">REG</th>
            <th className="col-timesheet">OT1</th>
            <th className="col-timesheet">OT2</th>
            <th className="col-timesheet">Drv</th>
            <th className="col-variance col-group-start">REG</th>
            <th className="col-variance">OT</th>
            <th className="col-variance">DBL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const rowBg = r.status === 'needs_review' ? 'rgba(124,45,18,0.15)'
                        : r.status === 'verified'      ? 'rgba(22,101,52,0.1)'
                        : 'transparent'
            return (
              <tr key={r.employee_id} style={{ background: rowBg }}>
                <td style={{ fontWeight: 600 }}>
                  {r.display_name}
                  {r.needs_expense_review && (
                    <span title="Expense review needed"
                      style={{ marginLeft: 5, color: '#f59e0b', fontSize: 10 }}>💰</span>
                  )}
                  {r.extra_expense_note && (
                    <div style={{ fontSize: 10, color: '#8b949e', fontWeight: 400, marginTop: 2 }}>
                      📝 {r.extra_expense_note}
                    </div>
                  )}
                </td>
                {/* Approved */}
                <td className="col-approved col-group-start">{fmtH(r.approved_reg)}</td>
                <td className="col-approved">{fmtH(r.approved_ot)}</td>
                <td className="col-approved">{fmtH(r.approved_dbl)}</td>
                <td className="col-approved">{fmtH(r.approved_travel)}</td>
                {/* Timesheet */}
                <td className="col-timesheet col-group-start">{fmtH(r.timesheet_reg)}</td>
                <td className="col-timesheet">{fmtH(r.timesheet_ot1)}</td>
                <td className="col-timesheet">{fmtH(r.timesheet_ot2)}</td>
                <td className="col-timesheet">{fmtH(r.timesheet_drive)}</td>
                {/* Variances */}
                <td className="col-variance col-group-start"><Variance v={r.reg_variance} /></td>
                <td className="col-variance"><Variance v={r.ot_variance} /></td>
                <td className="col-variance"><Variance v={r.dbl_variance} /></td>
                {/* Per diem */}
                <td style={{ color: '#8b949e' }}>
                  {r.per_diem_count > 0 ? r.per_diem_count : <span className="zero">—</span>}
                </td>
                {/* Sunday travel */}
                <td style={{ fontSize: 10, color: r.travel_sun_status === 'pending_next_pdf' ? '#f59e0b' : '#8b949e' }}>
                  {SUN_LABELS[r.travel_sun_status] || r.travel_sun_status}
                </td>
                {/* Status badge */}
                <td>
                  <span style={{
                    ...STATUS_STYLE[r.status],
                    fontSize: 10, padding: '2px 6px', borderRadius: 3,
                  }}>
                    {r.status.replace('_', ' ')}
                  </span>
                </td>
                {/* Action */}
                <td style={{ minWidth: 80 }}>
                  <VerifyAction
                    row={r}
                    periodId={periodId}
                    weekNum={weekNum}
                    onVerified={onVerified}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── main panel ────────────────────────────────────────────────────────────────

export default function ApprovedHoursPanel({ periodId, weekNum, onClose, onDone }) {
  const [weekInfo,       setWeekInfo]       = useState(null)
  const [payrollFile,    setPayrollFile]    = useState(null)
  const [travelFile,     setTravelFile]     = useState(null)
  const [payrollResult,  setPayrollResult]  = useState(null)
  const [travelResult,   setTravelResult]   = useState(null)
  const [importingPay,   setImportingPay]   = useState(false)
  const [importingTrav,  setImportingTrav]  = useState(false)
  const [verifying,      setVerifying]      = useState(false)
  const [verifySummary,  setVerifySummary]  = useState(null)
  const [verification,   setVerification]   = useState(null)

  const label = `Week ${weekNum} — Approved Hours`

  const loadVerification = async () => {
    try { setVerification(await getVerification(periodId, weekNum)) } catch { /* none yet */ }
  }

  useEffect(() => {
    if (!periodId) return
    getWeek(periodId, weekNum).then(setWeekInfo).catch(() => {})
    loadVerification()
  }, [periodId, weekNum])

  // Auto-import payroll PDF when file is picked
  useEffect(() => {
    if (!payrollFile) return
    ;(async () => {
      setImportingPay(true)
      setPayrollResult(null)
      try {
        const fd = new FormData()
        fd.append('file', payrollFile)
        fd.append('period_id', periodId)
        fd.append('week_num', weekNum)
        const res = await importPayrollPdf(fd)
        setPayrollResult({ ...res, filename: payrollFile.name })
        setWeekInfo(await getWeek(periodId, weekNum))
        onDone?.()
      } catch (err) {
        setPayrollResult({ error: err.response?.data?.detail || err.message })
      } finally {
        setImportingPay(false)
      }
    })()
  }, [payrollFile])

  // Auto-import travel PDF when file is picked
  useEffect(() => {
    if (!travelFile) return
    ;(async () => {
      setImportingTrav(true)
      setTravelResult(null)
      try {
        const fd = new FormData()
        fd.append('file', travelFile)
        fd.append('period_id', periodId)
        fd.append('week_num', weekNum)
        const res = await importTravelPdf(fd)
        setTravelResult({ ...res, filename: travelFile.name })
        setWeekInfo(await getWeek(periodId, weekNum))
        onDone?.()
      } catch (err) {
        setTravelResult({ error: err.response?.data?.detail || err.message })
      } finally {
        setImportingTrav(false)
      }
    })()
  }, [travelFile])

  const handleRunVerification = async () => {
    setVerifying(true)
    setVerifySummary(null)
    try {
      const summary = await runVerification(periodId, weekNum)
      setVerifySummary(summary)
      await loadVerification()
      onDone?.()
    } catch (err) {
      setVerifySummary({ error: err.response?.data?.detail || err.message })
    } finally {
      setVerifying(false)
    }
  }

  const hasPayrollPdf = weekInfo?.payroll_pdf_file || payrollResult?.success
  const hasTravelPdf  = weekInfo?.travel_pdf_file  || travelResult?.success

  return (
    <>
      <div className="panel-header">
        <h2>📊 {label}</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        {/* ── Payroll PDF ── */}
        <PdfDropZone
          label={`Wk ${weekNum} Payroll PDF`}
          file={payrollFile}
          result={payrollResult || (hasPayrollPdf && !payrollResult
            ? { success: true, filename: weekInfo.payroll_pdf_file, employee_count: '?' }
            : null)}
          importing={importingPay}
          onFile={f => { setPayrollFile(f); setPayrollResult(null) }}
        />

        {/* ── Travel PDF ── */}
        <PdfDropZone
          label={`Wk ${weekNum} Travel PDF`}
          file={travelFile}
          result={travelResult || (hasTravelPdf && !travelResult
            ? { success: true, filename: weekInfo.travel_pdf_file, employee_count: '?' }
            : null)}
          importing={importingTrav}
          onFile={f => { setTravelFile(f); setTravelResult(null) }}
        />

        {/* ── Verification ── */}
        <div style={{ marginTop: 6, borderTop: '1px solid #21262d', paddingTop: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div className="section-label" style={{ marginTop: 0, flex: 1 }}>
              Verification
            </div>
            <button
              className="btn btn-primary"
              style={{ padding: '4px 12px', fontSize: 11 }}
              onClick={handleRunVerification}
              disabled={verifying || !hasPayrollPdf}
            >
              {verifying ? '⏳ Running…' : '▶ Run Verification'}
            </button>
          </div>

          {!hasPayrollPdf && (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 8 }}>
              Import a payroll PDF first to enable verification.
            </div>
          )}

          {verifySummary && !verifySummary.error && (
            <div className="msg success" style={{ marginBottom: 8, fontSize: 11 }}>
              ✓ {verifySummary.total_employees} employees —&nbsp;
              <span style={{ color: '#22c55e' }}>{verifySummary.verified_count} verified</span>
              {verifySummary.needs_review_count > 0 && (
                <span style={{ color: '#f59e0b' }}> · {verifySummary.needs_review_count} need review</span>
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

          <VerificationTable
            rows={verification?.rows}
            periodId={periodId}
            weekNum={weekNum}
            onVerified={loadVerification}
          />
        </div>

      </div>
    </>
  )
}
