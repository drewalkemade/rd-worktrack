/**
 * TravelPdfPanel — focused view of data extracted from the travel PDF.
 *
 * Shows only what came from the Centerline travel PDF:
 *   - Per-employee daily travel hours (Mon–Sat raw columns)
 *   - Sunday attribution status (confirmed / pending / assumed)
 *   - Week total
 *
 * The travel PDF is Sun–Sat but the business week is Mon–Sun.
 * Sunday hours always belong to the prior Mon–Sun week — this panel
 * shows the Mon–Sat columns from the PDF plus the current week's Sunday
 * status so the owner can verify the attribution is correct.
 */
import { useState, useEffect } from 'react'
import { getTravelHours } from '../api'

function fmtH(n) {
  if (!n || n === 0) return <span className="zero">—</span>
  return n.toFixed(1)
}

const SUN_LABELS = {
  confirmed:              'confirmed',
  pending_next_pdf:       'pending PDF',
  assumed_from_timesheet: 'assumed TS',
  needs_employee_confirmation: 'needs confirm',
  'n/a':                  'n/a',
}

const SUN_COLOR = {
  confirmed:              '#22c55e',
  pending_next_pdf:       '#f59e0b',
  assumed_from_timesheet: '#a78bfa',
  needs_employee_confirmation: '#f87171',
}

export default function TravelPdfPanel({ periodId, weekNum, filename, onClose }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!periodId) return
    getTravelHours(periodId, weekNum)
      .then(setData)
      .catch(() => {})
  }, [periodId, weekNum])

  const rows = data?.rows || []

  return (
    <>
      <div className="panel-header">
        <h2>🚗 Wk {weekNum} — Travel PDF</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ marginBottom: 12 }}>
          <div className="section-label" style={{ marginTop: 0 }}>Source File</div>
          {filename
            ? <div className="msg success" style={{ marginBottom: 0 }}>✓ {filename}</div>
            : <div style={{ fontSize: 12, color: '#4b5563' }}>No travel PDF imported yet.</div>
          }
        </div>

        <div style={{ borderTop: '1px solid #21262d', paddingTop: 12 }}>
          <div className="section-label" style={{ marginTop: 0 }}>
            Travel Hours — Daily Breakdown
          </div>
          <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 8 }}>
            Raw columns from the travel PDF (Mon–Sat). Sunday belongs to the prior week —
            the Sun column shows raw hours; status shows how it was attributed.
          </div>

          {!rows.length ? (
            <div style={{ fontSize: 12, color: '#4b5563' }}>
              No travel data yet — import a travel PDF via the Approved Hours node.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="output-table" style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Mon</th>
                    <th>Tue</th>
                    <th>Wed</th>
                    <th>Thu</th>
                    <th>Fri</th>
                    <th>Sat</th>
                    <th style={{ color: '#a78bfa' }}>Total</th>
                    <th style={{ color: '#f59e0b', fontSize: 10 }}>Sun (prior)</th>
                    <th style={{ fontSize: 10 }}>Sun status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.employee}>
                      <td style={{ fontWeight: 600 }}>{r.employee}</td>
                      <td>{fmtH(r.mon)}</td>
                      <td>{fmtH(r.tue)}</td>
                      <td>{fmtH(r.wed)}</td>
                      <td>{fmtH(r.thu)}</td>
                      <td>{fmtH(r.fri)}</td>
                      <td>{fmtH(r.sat)}</td>
                      <td style={{ color: '#a78bfa', fontWeight: 700 }}>
                        {r.week_total > 0 ? r.week_total.toFixed(1) : '—'}
                      </td>
                      <td style={{ color: '#f59e0b' }}>
                        {r.sun > 0 ? r.sun.toFixed(1) : <span className="zero">—</span>}
                      </td>
                      <td style={{
                        fontSize: 10,
                        color: SUN_COLOR[r.sun_status] || '#8b949e',
                      }}>
                        {SUN_LABELS[r.sun_status] || r.sun_status || '—'}
                      </td>
                    </tr>
                  ))}
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
