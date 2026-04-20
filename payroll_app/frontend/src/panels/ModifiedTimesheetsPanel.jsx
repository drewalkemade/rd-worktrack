/**
 * ModifiedTimesheetsPanel — DrewEdit XLSX generation.
 *
 * Reads correction_log decisions for the period and generates corrected
 * employee XLSX files (_DrewEdit.xlsx) with notes already written in.
 * One file per employee that had corrections.
 *
 * Employees with no corrections are not included — their original
 * timesheet is already correct.
 *
 * Backend writer: pipeline/drewedit_writer.py (to be built).
 */
import { useState, useEffect, useCallback } from 'react'
import { getCorrections, getVerification } from '../api'

export default function ModifiedTimesheetsPanel({ periodId, onClose }) {
  const [wk1Corrections, setWk1Corrections] = useState([])
  const [wk2Corrections, setWk2Corrections] = useState([])
  const [verification,   setVerification]   = useState({ wk1: null, wk2: null })
  const [generating,     setGenerating]     = useState(false)
  const [error,          setError]          = useState(null)

  const load = useCallback(async () => {
    if (!periodId) return
    const [c1, c2, v1, v2] = await Promise.allSettled([
      getCorrections(periodId, 1),
      getCorrections(periodId, 2),
      getVerification(periodId, 1),
      getVerification(periodId, 2),
    ])
    if (c1.status === 'fulfilled') setWk1Corrections(c1.value.corrections || [])
    if (c2.status === 'fulfilled') setWk2Corrections(c2.value.corrections || [])
    setVerification({
      wk1: v1.status === 'fulfilled' ? v1.value : null,
      wk2: v2.status === 'fulfilled' ? v2.value : null,
    })
  }, [periodId])

  useEffect(() => { load() }, [periodId])

  // Dedupe by employee
  const employeesWithCorrections = {}
  for (const c of [...wk1Corrections, ...wk2Corrections]) {
    if (c.correction_type === 'approved_wins') {
      employeesWithCorrections[c.display_name] = employeesWithCorrections[c.display_name] || []
      employeesWithCorrections[c.display_name].push(c)
    }
  }
  const empNames = Object.keys(employeesWithCorrections).sort()

  return (
    <>
      <div className="panel-header">
        <h2>📊 Modified Timesheets</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">
        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 14, lineHeight: 1.6 }}>
          Generates corrected employee XLSX files with notes already written in,
          based on resolution decisions recorded in the Resolve node.
          One <em>_DrewEdit.xlsx</em> per employee with corrections.
        </div>

        {error && <div className="msg error" style={{ marginBottom: 10 }}>✗ {error}</div>}

        {empNames.length === 0 && (
          <div style={{ fontSize: 12, color: '#4b5563', marginBottom: 14 }}>
            No <em>approved_wins</em> corrections recorded — no DrewEdit files needed.
            {wk1Corrections.length === 0 && wk2Corrections.length === 0 &&
              ' Run the Resolve node first to record correction decisions.'}
          </div>
        )}

        {empNames.length > 0 && (
          <>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 8 }}>
              {empNames.length} employee{empNames.length !== 1 ? 's' : ''} with corrections to apply:
            </div>

            {empNames.map(name => {
              const corrections = employeesWithCorrections[name]
              return (
                <div key={name} style={{
                  padding: '10px 14px', marginBottom: 8,
                  background: '#161b22', border: '1px solid #21262d', borderRadius: 6,
                }}>
                  <div style={{ fontWeight: 600, fontSize: 12, color: '#e2e8f0', marginBottom: 6 }}>
                    {name}
                  </div>
                  {corrections.map((c, i) => (
                    <div key={i} style={{ fontSize: 10, color: '#6b7280', marginBottom: 2 }}>
                      {c.work_date} — {c.generated_note || 'correction noted'}
                    </div>
                  ))}
                </div>
              )
            })}

            <button
              className="btn btn-primary"
              style={{ fontSize: 12, padding: '7px 20px', marginTop: 6, marginBottom: 14 }}
              disabled={generating}
              onClick={() => setError('DrewEdit writer not yet implemented — coming in next phase.')}
            >
              {generating ? '… Generating' : '⬇ Generate DrewEdit Files'}
            </button>
          </>
        )}

        <div style={{
          padding: '8px 12px', background: '#0d1117', borderRadius: 6,
          border: '1px solid #21262d', fontSize: 11, color: '#4b5563', lineHeight: 1.7,
        }}>
          <strong style={{ color: '#8b949e' }}>How it works:</strong> For each employee with
          <em> approved_wins</em> corrections, opens their source XLSX, updates the corrected day
          cells to match approved hours, writes the generated note, and saves as
          <em> EmployeeName_DrewEdit.xlsx</em>. Original file is never overwritten.
        </div>
      </div>
    </>
  )
}
