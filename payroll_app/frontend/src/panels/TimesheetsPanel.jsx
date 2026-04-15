/**
 * TimesheetsPanel — upload biweekly timesheet XLSX files, import them,
 * and display the Week 1 (Mon–Sun) hours in a table matching
 * timesheet_export CSV format:
 *   Employee | REG | OT1 | OT2 | Drive | Sick | Vacation | Holiday | Non-Bill
 */
import { useState, useRef } from 'react'
import { importTimesheets, getWeek1Hours } from '../api'

function fmt(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return n.toFixed(1)
}

function HoursTable({ data }) {
  if (!data || !data.rows.length) return null

  // Column totals
  const cols = ['reg', 'ot1', 'ot2', 'drive', 'sick', 'vacation', 'holiday', 'nonbill']
  const totals = Object.fromEntries(cols.map(c => [c, data.rows.reduce((s, r) => s + (r[c] || 0), 0)]))

  return (
    <div style={{ marginTop: 16 }}>
      <div className="section-label" style={{ marginTop: 0 }}>
        Week 1 Hours — {data.week1_start} → {data.week1_ending}
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
            {data.rows.map(r => (
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
              {cols.map(c => (
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

export default function TimesheetsPanel({ periodId, onClose, onImportDone }) {
  const [files,      setFiles]      = useState([])    // File objects staged for upload
  const [importing,  setImporting]  = useState(false)
  const [results,    setResults]    = useState(null)  // import API response
  const [week1Data,  setWeek1Data]  = useState(null)  // week1-hours response
  const [dragOver,   setDragOver]   = useState(false)
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

    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))

      const res = await importTimesheets(fd)
      setResults(res)

      // Fetch Week 1 hours
      const pid = res.period_id || periodId
      if (pid) {
        try {
          const w1 = await getWeek1Hours(pid)
          setWeek1Data(w1)
        } catch {
          // No week1 data yet — that's ok
        }
      }

      onImportDone?.(res.period_id)
    } catch (err) {
      setResults({ error: err.response?.data?.detail || err.message })
    } finally {
      setImporting(false)
    }
  }

  // If a period is already selected, load existing week1 data on mount
  useState(() => {
    if (periodId && !week1Data) {
      getWeek1Hours(periodId).then(setWeek1Data).catch(() => {})
    }
  })

  return (
    <>
      <div className="panel-header">
        <h2>📋 Timesheets</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">
        <p style={{ fontSize: 12, color: '#8b949e', marginBottom: 16, lineHeight: 1.6 }}>
          Upload one or more biweekly employee timesheet XLSX files.
          The importer reads each employee's daily hours and splits them into
          <strong style={{ color: '#e2e8f0' }}> Week 1</strong> (Mon–Sun)
          and <strong style={{ color: '#e2e8f0' }}>Week 2</strong> automatically by date.
        </p>

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

        {/* Import results */}
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
          </div>
        )}

        {results?.error && (
          <div className="msg error" style={{ marginTop: 12 }}>✗ {results.error}</div>
        )}

        {/* Week 1 hours output table */}
        {week1Data && <HoursTable data={week1Data} />}

        {/* Load existing if period selected but no import yet */}
        {!week1Data && periodId && !results && (
          <div style={{ marginTop: 20, textAlign: 'center' }}>
            <button className="btn btn-ghost" onClick={() =>
              getWeek1Hours(periodId).then(setWeek1Data).catch(() =>
                setWeek1Data(null))
            }>
              Load existing Week 1 data
            </button>
          </div>
        )}
      </div>
    </>
  )
}
