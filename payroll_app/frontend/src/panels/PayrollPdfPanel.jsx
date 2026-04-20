/**
 * PayrollPdfPanel — focused view of data extracted from the payroll PDF.
 *
 * Shows only what came from the Centerline payroll approval PDF:
 *   - Per-employee weekly REG / OT / DBL totals
 *   - Expandable daily clock-in / clock-out rows
 *
 * Travel hours are NOT shown here (they come from a separate PDF).
 * This panel is a data-only read view — no uploads, no verification.
 * Upload lives in ApprovedHoursPanel.
 */
import { useState, useEffect } from 'react'
import { getApprovedHours } from '../api'

function fmtH(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return n.toFixed(1)
}

function EmployeeRow({ row }) {
  const [expanded, setExpanded] = useState(false)
  const total = (row.reg || 0) + (row.ot || 0) + (row.dbl || 0)

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
        <td style={{ color: '#58a6ff' }}>{fmtH(row.reg)}</td>
        <td>{fmtH(row.ot)}</td>
        <td>{fmtH(row.dbl)}</td>
        <td style={{ color: '#8b949e', fontWeight: 700 }}>{total > 0 ? total.toFixed(1) : '—'}</td>
      </tr>

      {expanded && row.daily.map(d => (
        <tr key={d.date} style={{ background: 'rgba(255,255,255,0.02)' }}>
          <td style={{ paddingLeft: 24, fontSize: 11, color: '#8b949e' }}>
            {d.day_name} {d.date}
            {d.is_dbl_day && (
              <span style={{ marginLeft: 5, fontSize: 10, color: '#f59e0b' }}>DBL</span>
            )}
          </td>
          <td colSpan={3} style={{ fontSize: 11, color: '#8b949e' }}>
            {d.clock_in && d.clock_out
              ? `${d.clock_in} → ${d.clock_out}`
              : <span className="zero">—</span>}
          </td>
          <td style={{ fontSize: 11, color: '#e2e8f0' }}>
            {d.total_hours > 0 ? d.total_hours.toFixed(2) : '—'}
          </td>
        </tr>
      ))}
    </>
  )
}

export default function PayrollPdfPanel({ periodId, weekNum, filename, onClose }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!periodId) return
    getApprovedHours(periodId, weekNum)
      .then(setData)
      .catch(() => {})
  }, [periodId, weekNum])

  // Only show rows that have customer_hours (reg/ot/dbl) — skip travel-only rows
  const rows = (data?.rows || []).filter(r => (r.reg || 0) + (r.ot || 0) + (r.dbl || 0) > 0 || r.daily?.length > 0)

  return (
    <>
      <div className="panel-header">
        <h2>📄 Wk {weekNum} — Payroll PDF</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ marginBottom: 12 }}>
          <div className="section-label" style={{ marginTop: 0 }}>Source File</div>
          {filename
            ? <div className="msg success" style={{ marginBottom: 0 }}>✓ {filename}</div>
            : <div style={{ fontSize: 12, color: '#4b5563' }}>No payroll PDF imported yet.</div>
          }
        </div>

        <div style={{ borderTop: '1px solid #21262d', paddingTop: 12 }}>
          <div className="section-label" style={{ marginTop: 0 }}>
            Approved Hours — Labor Only
          </div>
          <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 8 }}>
            REG / OT / DBL from the payroll PDF. Travel is a separate column (see Travel PDF node).
            Click a row to expand daily clock-in/out detail.
          </div>

          {!rows.length ? (
            <div style={{ fontSize: 12, color: '#4b5563' }}>
              No approved hours data yet — import a payroll PDF via the Approved Hours node.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="output-table" style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th style={{ color: '#58a6ff' }}>REG</th>
                    <th>OT</th>
                    <th>DBL</th>
                    <th>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => <EmployeeRow key={r.employee} row={r} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {data?.week_ending && (
          <div style={{ fontSize: 10, color: '#4b5563', marginTop: 8 }}>
            Week ending {data.week_ending}
          </div>
        )}

        <div style={{
          marginTop: 16, padding: '8px 12px',
          background: '#0d1117', borderRadius: 6,
          border: '1px solid #21262d', fontSize: 11, color: '#4b5563',
        }}>
          Upload PDFs and view the combined approved + travel table in the
          <strong style={{ color: '#8b949e' }}> Approved Hours</strong> node.
        </div>

      </div>
    </>
  )
}
