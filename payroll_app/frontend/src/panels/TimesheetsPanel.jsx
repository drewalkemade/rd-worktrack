/**
 * TimesheetsPanel — upload biweekly timesheet XLSX files, import them,
 * and display the Week 1 (Mon–Sun) hours in a table matching
 * timesheet_export CSV format:
 *   Employee | REG | OT1 | OT2 | Drive | Sick | Vacation | Holiday | Non-Bill
 */
import { useState, useRef } from 'react'
import { importTimesheets, getWeek1Hours, getWeek2Hours, getPeriodExpenses } from '../api'
import { downloadCsv } from '../utils/csv'

function fmt(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return n.toFixed(1)
}

const HOUR_COLS = ['reg', 'ot1', 'ot2', 'drive', 'sick', 'vacation', 'holiday', 'nonbill']

function HoursTable({ label, dateRange, rows }) {
  if (!rows || !rows.length) return null

  const totals = Object.fromEntries(HOUR_COLS.map(c => [c, rows.reduce((s, r) => s + (r[c] || 0), 0)]))

  return (
    <div style={{ marginTop: 16 }}>
      <div className="section-label" style={{ marginTop: 0 }}>
        {label} — {dateRange}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="output-table">
          <thead>
            <tr>
              <th>Employee</th>
              <th>REG</th>
              <th>OT1</th>
              <th>OT2</th>
              <th>Drive</th>
              <th>Sick</th>
              <th>Vacation</th>
              <th>Holiday</th>
              <th>Non-Bill</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.employee}>
                <td>{r.employee}</td>
                <td>{fmt(r.reg)}</td>
                <td>{fmt(r.ot1)}</td>
                <td>{fmt(r.ot2)}</td>
                <td>{fmt(r.drive)}</td>
                <td>{fmt(r.sick)}</td>
                <td>{fmt(r.vacation)}</td>
                <td>{fmt(r.holiday)}</td>
                <td>{fmt(r.nonbill)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td style={{ color: '#8b949e', fontWeight: 700 }}>Total</td>
              {HOUR_COLS.map(c => (
                <td key={c} style={{ fontWeight: 700, color: '#58a6ff' }}>
                  {totals[c] > 0 ? totals[c].toFixed(1) : <span className="zero">—</span>}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

const RECEIPT_COLOR = {
  not_required: '#4b5563',
  received:     '#166534',
  missing:      '#7f1d1d',
}

function ExpenseTable({ label, items }) {
  if (!items || !items.length) return null

  const cadTotal = items.filter(i => i.currency === 'CAD').reduce((s, i) => s + i.amount, 0)
  const usdTotal = items.filter(i => i.currency === 'USD').reduce((s, i) => s + i.amount, 0)

  return (
    <div style={{ marginTop: 14 }}>
      <div className="section-label" style={{ marginTop: 0 }}>{label}</div>
      <div style={{ overflowX: 'auto' }}>
        <table className="output-table">
          <thead>
            <tr>
              <th>Employee</th>
              <th>Date</th>
              <th>Category</th>
              <th>Description</th>
              <th style={{ textAlign: 'right' }}>Qty</th>
              <th style={{ textAlign: 'right' }}>Amount</th>
              <th>Cur</th>
              <th>Receipt</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r, i) => (
              <tr key={i}>
                <td>{r.employee}</td>
                <td style={{ color: '#8b949e', whiteSpace: 'nowrap' }}>{r.work_date || '—'}</td>
                <td style={{ fontSize: 11 }}>{r.category}</td>
                <td style={{ fontSize: 11, color: '#8b949e' }}>{r.description || '—'}</td>
                <td style={{ textAlign: 'right' }}>{r.quantity !== 1 ? r.quantity : '—'}</td>
                <td style={{ textAlign: 'right' }}>{r.amount.toFixed(2)}</td>
                <td style={{ color: '#8b949e' }}>{r.currency}</td>
                <td>
                  <span style={{
                    fontSize: 10,
                    padding: '1px 5px',
                    borderRadius: 3,
                    background: RECEIPT_COLOR[r.receipt_status] || '#21262d',
                    color: '#fff',
                  }}>
                    {r.requires_receipt ? r.receipt_status : 'n/a'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={5} style={{ color: '#8b949e', fontWeight: 700 }}>Total</td>
              <td style={{ textAlign: 'right', fontWeight: 700, color: '#58a6ff' }}>
                {cadTotal > 0 && <div>CAD {cadTotal.toFixed(2)}</div>}
                {usdTotal > 0 && <div>USD {usdTotal.toFixed(2)}</div>}
              </td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

export default function TimesheetsPanel({ periodId, onClose, onImportDone }) {
  const [files,      setFiles]      = useState([])    // File objects staged for upload
  const [importing,  setImporting]  = useState(false)
  const [results,    setResults]    = useState(null)  // import API response
  const [week1Data,  setWeek1Data]  = useState(null)  // week1-hours response
  const [week2Data,  setWeek2Data]  = useState(null)  // week2-hours response
  const [expenses,   setExpenses]   = useState(null)  // all expense_items for period
  const [dragOver,   setDragOver]   = useState(false)
  const [showReimport, setShowReimport] = useState(false)  // toggle re-import section
  const fileInputRef = useRef()

  const addFiles = (incoming) => {
    const xlsx = Array.from(incoming).filter(f => f.name.endsWith('.xlsx'))
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name))
      return [...prev, ...xlsx.filter(f => !names.has(f.name))]
    })
  }

  const removeFile = (name) => setFiles(prev => prev.filter(f => f.name !== name))

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }

  const handleImport = async () => {
    if (!files.length) return
    setImporting(true)
    setResults(null)
    setWeek1Data(null)
    setWeek2Data(null)
    setExpenses(null)

    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))

      const res = await importTimesheets(fd)
      setResults(res)

      // Fetch both weeks
      const pid = res.period_id || periodId
      if (pid) {
        try { setWeek1Data(await getWeek1Hours(pid)) } catch { /* no data yet */ }
        try { setWeek2Data(await getWeek2Hours(pid)) } catch { /* no data yet */ }
        try { setExpenses(await getPeriodExpenses(pid)) } catch { /* no data yet */ }
      }

      onImportDone?.(res.period_id)
    } catch (err) {
      setResults({ error: err.response?.data?.detail || err.message })
    } finally {
      setImporting(false)
    }
  }

  // If a period is already selected, load existing data on mount
  useState(() => {
    if (periodId) {
      getWeek1Hours(periodId).then(setWeek1Data).catch(() => {})
      getWeek2Hours(periodId).then(setWeek2Data).catch(() => {})
      getPeriodExpenses(periodId).then(setExpenses).catch(() => {})
    }
  })

  return (
    <>
      <div className="panel-header">
        <h2>📋 Timesheets</h2>
        {(week1Data || week2Data) && (
          <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => {
              const rows = [['Employee','Week','REG','OT1','OT2','Drive','Sick','Vacation','Holiday','NonBill']]
              for (const d of [week1Data, week2Data].filter(Boolean)) {
                const wk = d.week1_start ? 1 : 2
                for (const r of d.rows || []) {
                  rows.push([r.employee,wk,r.reg||0,r.ot1||0,r.ot2||0,r.drive||0,r.sick||0,r.vacation||0,r.holiday||0,r.nonbill||0])
                }
              }
              downloadCsv(rows, 'debug_timesheets.csv')
            }}>↓ Debug CSV</button>
        )}
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        {/* ── If data is already loaded, show it first ── */}
        {(week1Data || week2Data) && !results && (
          <>
            {week1Data && (
              <HoursTable
                label="Week 1 Hours"
                dateRange={`${week1Data.week1_start} → ${week1Data.week1_ending}`}
                rows={week1Data.rows}
              />
            )}
            {expenses && (
              <ExpenseTable
                label="Week 1 Expenses"
                items={expenses.items.filter(i => i.week === 1)}
              />
            )}
            {week2Data && week2Data.rows.length > 0 && (
              <HoursTable
                label="Week 2 Hours"
                dateRange={`${week2Data.week2_start} → ${week2Data.week2_ending}`}
                rows={week2Data.rows}
              />
            )}
            {expenses && (
              <ExpenseTable
                label="Week 2 Expenses"
                items={expenses.items.filter(i => i.week === 2)}
              />
            )}

            {/* Re-import toggle */}
            <div style={{ marginTop: 20, borderTop: '1px solid #21262d', paddingTop: 14 }}>
              <button
                className="btn btn-ghost"
                style={{ fontSize: 12 }}
                onClick={() => setShowReimport(r => !r)}
              >
                {showReimport ? '▾ Hide re-import' : '▸ Re-import / Replace Files'}
              </button>
            </div>
          </>
        )}

        {/* ── Upload section — always shown on first load; toggleable after ── */}
        {(!week1Data && !week2Data || showReimport || results) && (
          <>
            {(week1Data || week2Data) && (
              <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 10, marginTop: 4 }}>
                ⚠ Re-importing will replace existing timesheet data for any matched employees.
              </div>
            )}

            {!(week1Data || week2Data) && (
              <p style={{ fontSize: 12, color: '#8b949e', marginBottom: 16, lineHeight: 1.6 }}>
                Upload one or more biweekly employee timesheet XLSX files.
                The importer reads each employee's daily hours and splits them into
                <strong style={{ color: '#e2e8f0' }}> Week 1</strong> (Mon–Sun)
                and <strong style={{ color: '#e2e8f0' }}>Week 2</strong> automatically by date.
              </p>
            )}

            {/* Drop zone */}
            <div
              className={`drop-zone ${dragOver ? 'drag-over' : ''}`}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                multiple
                style={{ display: 'none' }}
                onChange={e => addFiles(e.target.files)}
              />
              <div style={{ fontSize: 28, marginBottom: 6 }}>📂</div>
              <div>Drop XLSX files here or click to browse</div>
              <div style={{ fontSize: 10, marginTop: 4, color: '#4b5563' }}>
                Accepts multiple files — one per employee
              </div>
            </div>

            {/* Staged file list */}
            {files.length > 0 && (
              <>
                <div className="section-label">Staged files ({files.length})</div>
                <div>
                  {files.map(f => (
                    <div key={f.name} className="file-chip">
                      📄
                      <span style={{ color: '#e2e8f0', flex: 1 }}>{f.name}</span>
                      <span style={{ fontSize: 10, color: '#4b5563' }}>
                        {(f.size / 1024).toFixed(0)} KB
                      </span>
                      <span
                        style={{ color: '#ef4444', cursor: 'pointer', marginLeft: 4 }}
                        onClick={() => removeFile(f.name)}
                      >×</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Import button */}
            <div style={{ marginTop: 16, display: 'flex', gap: 10, alignItems: 'center' }}>
              <button
                className="btn btn-primary"
                onClick={handleImport}
                disabled={importing || files.length === 0}
              >
                {importing ? '⏳ Importing…' : '▶  Import Timesheets'}
              </button>
              {files.length > 0 && (
                <button className="btn btn-ghost" onClick={() => setFiles([])}>
                  Clear
                </button>
              )}
            </div>
          </>
        )}

        {/* ── Import results (shown after any import) ── */}
        {results && !results.error && (
          <div style={{ marginTop: 16 }}>
            {results.files?.map(f => (
              <div key={f.filename}>
                <div className={`msg ${f.success ? 'success' : 'error'}`}>
                  {f.success ? '✓' : '✗'} {f.filename}
                  {f.success && ` — ${f.employee_count} employee(s) imported`}
                </div>
                {f.warnings?.map((w, i) => (
                  <div key={i} className="msg warn">⚠ {w}</div>
                ))}
                {f.errors?.map((e, i) => (
                  <div key={i} className="msg error">✗ {e}</div>
                ))}
              </div>
            ))}

            {/* Show updated data after re-import */}
            {week1Data && (
              <HoursTable
                label="Week 1 Hours"
                dateRange={`${week1Data.week1_start} → ${week1Data.week1_ending}`}
                rows={week1Data.rows}
              />
            )}
            {expenses && (
              <ExpenseTable
                label="Week 1 Expenses"
                items={expenses.items.filter(i => i.week === 1)}
              />
            )}
            {week2Data && week2Data.rows.length > 0 && (
              <HoursTable
                label="Week 2 Hours"
                dateRange={`${week2Data.week2_start} → ${week2Data.week2_ending}`}
                rows={week2Data.rows}
              />
            )}
            {expenses && (
              <ExpenseTable
                label="Week 2 Expenses"
                items={expenses.items.filter(i => i.week === 2)}
              />
            )}
          </div>
        )}

        {results?.error && (
          <div className="msg error" style={{ marginTop: 12 }}>✗ {results.error}</div>
        )}

        {/* Load existing if period selected but no import yet and no data */}
        {!week1Data && !week2Data && periodId && !results && (
          <div style={{ marginTop: 20, textAlign: 'center' }}>
            <button className="btn btn-ghost" onClick={() => {
              getWeek1Hours(periodId).then(setWeek1Data).catch(() => {})
              getWeek2Hours(periodId).then(setWeek2Data).catch(() => {})
              getPeriodExpenses(periodId).then(setExpenses).catch(() => {})
            }}>
              Load existing data
            </button>
          </div>
        )}
      </div>
    </>
  )
}
