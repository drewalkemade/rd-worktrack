/**
 * ApprovedHoursPanel — import PDFs and review adjusted approved hours.
 *
 * Three sections:
 *   1. Adjusted Approved Hours — PDF total minus per-day travel = labor hours.
 *      This is the canonical number carried forward to Compare and Resolve.
 *      Travel is always Regular time and does NOT count toward the OT threshold.
 *
 *   2. Payroll PDF Extract — raw clock-in/out rows as parsed from the payroll PDF.
 *
 *   3. Travel PDF Extract — raw per-day travel hours as parsed from the travel PDF.
 *      Travel PDF covers Sun–Sat; Sunday belongs to the prior business week.
 */
import { useState, useEffect, useRef } from 'react'
import { getWeek, getApprovedHours, importPayrollPdf, importTravelPdf } from '../api'
import { downloadCsv } from '../utils/csv'


// ── helpers ───────────────────────────────────────────────────────────────────

function fmtH(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return Number(n).toFixed(2)
}

function fmtHPlain(n) {
  if (!n || n === 0) return '—'
  return Number(n).toFixed(2)
}

const SUN_LABELS = {
  confirmed:              'confirmed',
  pending_next_pdf:       'pending PDF',
  assumed_from_timesheet: 'assumed TS',
  'n/a':                  'n/a',
}


// ── PDF drop zone ─────────────────────────────────────────────────────────────

function PdfDropZone({ label, onFile, file, result, importing }) {
  const [dragOver, setDragOver] = useState(false)
  const ref = useRef()

  const pick = (incoming) => {
    const f = Array.from(incoming).find(f => f.name.toLowerCase().endsWith('.pdf'))
    if (f) onFile(f)
  }

  const alreadyLoaded = result?.success

  return (
    <div style={{ marginBottom: 10 }}>
      <div className="section-label" style={{ marginTop: 0 }}>{label}</div>

      {alreadyLoaded ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="msg success" style={{ flex: 1, marginBottom: 0 }}>
            ✓ {result.filename}
            {result.employee_count && result.employee_count !== '?'
              ? ` — ${result.employee_count} employee(s)` : ''}
          </div>
          <button
            className="btn btn-ghost"
            style={{ fontSize: 10, padding: '2px 8px', whiteSpace: 'nowrap' }}
            onClick={() => ref.current?.click()}
          >
            Replace
          </button>
          <input ref={ref} type="file" accept=".pdf" style={{ display: 'none' }}
            onChange={e => pick(e.target.files)} />
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
          {result?.warnings?.map((w, i) => (
            <div key={i} className="msg warn" style={{ marginTop: 4 }}>⚠ {w}</div>
          ))}
        </>
      )}

      {importing && <div style={{ fontSize: 11, color: '#8b949e', marginTop: 6 }}>⏳ Importing…</div>}
    </div>
  )
}


// ── Section 1: Adjusted Approved Hours ───────────────────────────────────────
// Shows labor_day = pdf_total - travel_day per day, plus weekly labor and travel totals.

function AdjustedEmployeeRow({ row }) {
  const [expanded, setExpanded] = useState(false)

  const totalTravel = row.travel || 0
  // Weekly labor = sum of labor_day across all days (or fall back to reg+ot+dbl if no daily data)
  const totalLabor = row.daily.length
    ? row.daily.reduce((s, d) => s + (d.labor_day || 0), 0)
    : (row.reg || 0) + (row.ot || 0) + (row.dbl || 0)
  const totalPdf   = totalLabor + totalTravel

  return (
    <>
      <tr
        style={{ cursor: row.daily.length ? 'pointer' : 'default' }}
        onClick={() => row.daily.length && setExpanded(e => !e)}
      >
        <td style={{ fontWeight: 600 }}>
          {row.daily.length > 0 && (
            <span style={{ marginRight: 5, fontSize: 10, color: '#4b5563' }}>
              {expanded ? '▾' : '▸'}
            </span>
          )}
          {row.employee}
        </td>
        <td style={{ color: '#22c55e', fontWeight: 600 }}>
          {totalLabor > 0 ? totalLabor.toFixed(2) : '—'}
        </td>
        <td style={{ color: '#a78bfa', fontStyle: 'italic' }}>
          {fmtH(totalTravel)}
        </td>
        <td style={{ color: '#8b949e' }}>
          {totalPdf > 0 ? totalPdf.toFixed(2) : '—'}
        </td>
        {row.sun_status && (
          <td style={{
            fontSize: 10,
            color: row.sun_status === 'pending_next_pdf' ? '#f59e0b' : '#8b949e',
          }}>
            {SUN_LABELS[row.sun_status] || row.sun_status}
          </td>
        )}
      </tr>

      {expanded && row.daily.map(d => (
        <tr key={d.date} style={{ background: 'rgba(255,255,255,0.02)' }}>
          <td style={{ paddingLeft: 24, fontSize: 11, color: '#8b949e' }}>
            {d.day_name}&nbsp;
            <span style={{ color: '#4b5563' }}>{d.date?.slice(5)}</span>
            {d.is_dbl_day && (
              <span style={{ marginLeft: 5, fontSize: 10, color: '#f59e0b', fontWeight: 700 }}>DBL</span>
            )}
          </td>
          <td style={{ fontSize: 11, color: '#22c55e' }}>
            {d.labor_day > 0 ? d.labor_day.toFixed(2) : '—'}
          </td>
          <td style={{ fontSize: 11, color: '#a78bfa', fontStyle: 'italic' }}>
            {d.travel_day > 0 ? d.travel_day.toFixed(2) : '—'}
          </td>
          <td style={{ fontSize: 11, color: '#8b949e' }}>
            {d.pdf_total > 0 ? d.pdf_total.toFixed(2) : '—'}
          </td>
          <td />
        </tr>
      ))}
    </>
  )
}

function AdjustedHoursTable({ rows, hasSunStatus }) {
  if (!rows || !rows.length) return (
    <div style={{ color: '#4b5563', fontSize: 12, marginTop: 8 }}>
      Import a payroll PDF to see adjusted approved hours.
    </div>
  )

  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table className="output-table" style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>Employee</th>
            <th style={{ color: '#22c55e' }}>Labor Hrs</th>
            <th style={{ color: '#a78bfa', fontStyle: 'italic' }}>Travel Hrs</th>
            <th style={{ color: '#8b949e' }}>PDF Total</th>
            {hasSunStatus && <th>Sun</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <AdjustedEmployeeRow key={r.employee} row={r} />
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 10, color: '#4b5563', marginTop: 6, lineHeight: 1.6 }}>
        Labor = PDF total − travel. Travel is always Regular time and does NOT count
        toward the overtime threshold. Full REG/OT/DBL reclassification happens in Reconcile.
      </div>
    </div>
  )
}


// ── Section 2: Raw Payroll PDF Extract ────────────────────────────────────────

function PayrollPdfTable({ rows }) {
  if (!rows || !rows.length) return (
    <div style={{ color: '#4b5563', fontSize: 12, marginTop: 8 }}>
      No payroll PDF data.
    </div>
  )

  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table className="output-table" style={{ fontSize: 11 }}>
        <thead>
          <tr>
            <th>Employee</th>
            <th>Day</th>
            <th>Date</th>
            <th>Clock In</th>
            <th>Clock Out</th>
            <th>Hours</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r =>
            r.daily.map(d => (
              <tr key={`${r.employee}-${d.date}`}>
                <td style={{ fontWeight: 600, color: '#e2e8f0' }}>{r.employee}</td>
                <td style={{ color: '#8b949e' }}>
                  {d.day_name}
                  {d.is_dbl_day && (
                    <span style={{ marginLeft: 5, fontSize: 9, color: '#f59e0b', fontWeight: 700 }}>DBL</span>
                  )}
                </td>
                <td style={{ color: '#4b5563' }}>{d.date?.slice(5)}</td>
                <td style={{ color: '#8b949e', fontFamily: 'monospace' }}>{d.clock_in || '—'}</td>
                <td style={{ color: '#8b949e', fontFamily: 'monospace' }}>{d.clock_out || '—'}</td>
                <td style={{ color: '#58a6ff' }}>{d.pdf_total > 0 ? d.pdf_total.toFixed(2) : '—'}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}


// ── Section 3: Raw Travel PDF Extract ────────────────────────────────────────

function TravelPdfTable({ rows }) {
  if (!rows || !rows.length) return (
    <div style={{ color: '#4b5563', fontSize: 12, marginTop: 8 }}>
      No travel PDF imported — travel defaults to 0.
    </div>
  )

  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table className="output-table" style={{ fontSize: 11 }}>
        <thead>
          <tr>
            <th>Employee</th>
            <th style={{ color: '#6b7280', fontStyle: 'italic' }}>Sun (prior)</th>
            <th>Mon</th>
            <th>Tue</th>
            <th>Wed</th>
            <th>Thu</th>
            <th>Fri</th>
            <th>Sat</th>
            <th style={{ color: '#a78bfa' }}>Sun (wk end)</th>
            <th style={{ color: '#8b949e' }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.employee}>
              <td style={{ fontWeight: 600, color: '#e2e8f0' }}>{r.employee}</td>
              <td style={{ color: '#374151', fontStyle: 'italic' }}>{fmtHPlain(r.sun_prior)}</td>
              <td style={{ color: '#a78bfa' }}>{fmtHPlain(r.mon)}</td>
              <td style={{ color: '#a78bfa' }}>{fmtHPlain(r.tue)}</td>
              <td style={{ color: '#a78bfa' }}>{fmtHPlain(r.wed)}</td>
              <td style={{ color: '#a78bfa' }}>{fmtHPlain(r.thu)}</td>
              <td style={{ color: '#a78bfa' }}>{fmtHPlain(r.fri)}</td>
              <td style={{ color: '#a78bfa' }}>{fmtHPlain(r.sat)}</td>
              <td style={{
                color: r.current_sun_status === 'pending_next_pdf' ? '#f59e0b'
                     : r.current_sun > 0 ? '#a78bfa' : '#374151',
                fontStyle: 'italic',
                fontSize: 10,
              }}>
                {r.current_sun > 0
                  ? `${r.current_sun.toFixed(2)} (${SUN_LABELS[r.current_sun_status] || r.current_sun_status})`
                  : SUN_LABELS[r.current_sun_status] || '—'
                }
              </td>
              <td style={{ color: '#8b949e', fontWeight: 600 }}>
                {r.week_total > 0 ? r.week_total.toFixed(2) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 10, color: '#4b5563', marginTop: 6, lineHeight: 1.6 }}>
        Travel PDF covers Sun–Sat. <em>Sun (prior)</em> belongs to the prior Mon–Sun business week.
        <em> Sun (wk end)</em> is confirmed from the following week's travel PDF, or assumed from timesheet.
      </div>
    </div>
  )
}


// ── Collapsible section wrapper ───────────────────────────────────────────────

function Section({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ marginTop: 16, borderTop: '1px solid #21262d', paddingTop: 12 }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', marginBottom: open ? 6 : 0 }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ fontSize: 10, color: '#4b5563' }}>{open ? '▾' : '▸'}</span>
        <div className="section-label" style={{ marginTop: 0, marginBottom: 0 }}>{title}</div>
      </div>
      {open && children}
    </div>
  )
}


// ── Main panel ────────────────────────────────────────────────────────────────

export default function ApprovedHoursPanel({ periodId, weekNum, onClose, onDone }) {
  const [weekInfo,      setWeekInfo]      = useState(null)
  const [payrollFile,   setPayrollFile]   = useState(null)
  const [travelFile,    setTravelFile]    = useState(null)
  const [payrollResult, setPayrollResult] = useState(null)
  const [travelResult,  setTravelResult]  = useState(null)
  const [importingPay,  setImportingPay]  = useState(false)
  const [importingTrav, setImportingTrav] = useState(false)
  const [hoursData,     setHoursData]     = useState(null)

  const label = `Week ${weekNum} — Approved Hours`

  const loadData = async () => {
    try {
      const data = await getApprovedHours(periodId, weekNum)
      setHoursData(data)
    } catch { /* no data yet */ }
  }

  useEffect(() => {
    if (!periodId) return
    getWeek(periodId, weekNum).then(setWeekInfo).catch(() => {})
    loadData()
  }, [periodId, weekNum])

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
        await loadData()
        onDone?.()
      } catch (err) {
        setPayrollResult({ error: err.response?.data?.detail || err.message })
      } finally {
        setImportingPay(false)
      }
    })()
  }, [payrollFile])

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
        await loadData()
        onDone?.()
      } catch (err) {
        setTravelResult({ error: err.response?.data?.detail || err.message })
      } finally {
        setImportingTrav(false)
      }
    })()
  }, [travelFile])

  const hasPayrollPdf = weekInfo?.payroll_pdf_file || payrollResult?.success
  const hasTravelPdf  = weekInfo?.travel_pdf_file  || travelResult?.success
  const hasSunStatus  = hoursData?.rows?.some(r => r.sun_status)

  return (
    <>
      <div className="panel-header">
        <h2>📊 {label}</h2>
        {hoursData && (
          <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => {
              const rows = [['Employee','Date','Day','PDF Total','Travel','Labor','Clock In','Clock Out','DBL']]
              for (const r of hoursData.rows || []) {
                for (const d of r.daily || []) {
                  rows.push([r.employee,d.date,d.day_name,d.pdf_total,d.travel_day,d.labor_day,d.clock_in||'',d.clock_out||'',d.is_dbl_day?1:0])
                }
              }
              downloadCsv(rows, `debug_approved_wk${weekNum}.csv`)
            }}>↓ Debug CSV</button>
        )}
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        {/* ── PDF inputs ── */}
        <PdfDropZone
          label={`Wk ${weekNum} Payroll PDF`}
          file={payrollFile}
          result={payrollResult || (hasPayrollPdf && !payrollResult
            ? { success: true, filename: weekInfo?.payroll_pdf_file || 'loaded' }
            : null)}
          importing={importingPay}
          onFile={f => { setPayrollFile(f); setPayrollResult(null) }}
        />

        <PdfDropZone
          label={`Wk ${weekNum} Travel PDF`}
          file={travelFile}
          result={travelResult || (hasTravelPdf && !travelResult
            ? { success: true, filename: weekInfo?.travel_pdf_file || 'loaded' }
            : null)}
          importing={importingTrav}
          onFile={f => { setTravelFile(f); setTravelResult(null) }}
        />

        {hoursData ? (
          <>
            {/* ── Section 1: Adjusted Approved Hours ── */}
            <Section title="Adjusted Approved Hours (Labor = PDF − Travel)">
              <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 6, lineHeight: 1.6 }}>
                Travel is subtracted from the payroll PDF total per day. These adjusted labor hours
                are carried forward to Compare and Resolve. Click a row to expand daily detail.
              </div>
              <AdjustedHoursTable rows={hoursData.rows} hasSunStatus={hasSunStatus} />
            </Section>

            {/* ── Section 2: Raw Payroll PDF Extract ── */}
            <Section title="Payroll PDF Extract (raw clock-in/out)" defaultOpen={false}>
              <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 6 }}>
                Raw totals as parsed from the payroll PDF. Includes travel hours.
              </div>
              <PayrollPdfTable rows={hoursData.rows} />
            </Section>

            {/* ── Section 3: Raw Travel PDF Extract ── */}
            <Section title="Travel PDF Extract (raw per-day travel)" defaultOpen={false}>
              <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 6 }}>
                Raw per-day travel hours from the travel PDF (Sun–Sat range). Used to split
                travel from labor in the adjusted table above.
              </div>
              <TravelPdfTable rows={hoursData.travel_rows} />
            </Section>

            {hoursData.week_ending && (
              <div style={{ fontSize: 10, color: '#4b5563', marginTop: 12 }}>
                Week ending {hoursData.week_ending}
                {hoursData.week_start && ` (${hoursData.week_start} – ${hoursData.week_ending})`}
              </div>
            )}
          </>
        ) : (
          !hasPayrollPdf && (
            <div style={{ fontSize: 11, color: '#8b949e', marginTop: 14 }}>
              Import a payroll PDF to see approved hours.
            </div>
          )
        )}

        <div style={{
          marginTop: 16, padding: '8px 12px',
          background: '#0d1117', borderRadius: 6,
          border: '1px solid #21262d', fontSize: 11, color: '#4b5563',
        }}>
          Day-level comparison with timesheets and hour corrections are in the
          <strong style={{ color: '#8b949e' }}> Compare</strong> and
          <strong style={{ color: '#8b949e' }}> Resolve</strong> nodes.
          Full REG/OT/DBL reclassification (accounting for travel) happens in
          <strong style={{ color: '#8b949e' }}> Reconcile</strong>.
        </div>

      </div>
    </>
  )
}
