/**
 * MergePanel — biweekly merge and reconciliation.
 *
 * Requires both Week 1 and Week 2 to be fully verified before
 * reconciliation can run. Reconciliation combines both weeks into the
 * biweekly payroll run and generates the Sage 50 export data.
 *
 * Reconciliation is handled by pipeline/reconciler.py.
 */
import { useState, useEffect, useCallback } from 'react'
import { getVerification } from '../api'
import axios from 'axios'

const api = axios.create({ baseURL: 'http://localhost:8000' })

function StatusBadge({ verified, total, label }) {
  const color = verified === total && total > 0 ? '#22c55e'
              : verified > 0                    ? '#f59e0b'
              : '#4b5563'
  return (
    <div style={{
      flex: 1, padding: '12px 16px',
      background: '#161b22', border: `1px solid ${color}33`,
      borderRadius: 8, textAlign: 'center',
    }}>
      <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>
        {verified}/{total}
      </div>
      <div style={{ fontSize: 10, color }}>
        {verified === total && total > 0
          ? '✓ verified'
          : total === 0 ? 'no data' : 'in progress'}
      </div>
    </div>
  )
}

export default function MergePanel({ periodId, onClose, onDone }) {
  const [wk1, setWk1]         = useState(null)
  const [wk2, setWk2]         = useState(null)
  const [running, setRunning] = useState(false)
  const [result,  setResult]  = useState(null)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    if (!periodId) return
    const [v1, v2] = await Promise.allSettled([
      getVerification(periodId, 1),
      getVerification(periodId, 2),
    ])
    if (v1.status === 'fulfilled') setWk1(v1.value)
    if (v2.status === 'fulfilled') setWk2(v2.value)
  }, [periodId])

  useEffect(() => { load() }, [periodId])

  const wk1Rows     = wk1?.rows || []
  const wk2Rows     = wk2?.rows || []
  const wk1Verified = wk1Rows.filter(r => r.status === 'verified').length
  const wk2Verified = wk2Rows.filter(r => r.status === 'verified').length
  const bothReady   = wk1Rows.length > 0 && wk2Rows.length > 0 &&
                      wk1Verified === wk1Rows.length && wk2Verified === wk2Rows.length

  const handleReconcile = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const r = await api.post(`/api/periods/${periodId}/reconcile`).then(r => r.data)
      setResult(r)
      onDone?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <div className="panel-header">
        <h2>🔗 Merge — Biweekly Reconciliation</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">
        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 16, lineHeight: 1.6 }}>
          Combines both weeks into the biweekly payroll run. Both weeks must be
          fully verified before reconciliation can proceed.
        </div>

        {/* Week status badges */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <StatusBadge label="Week 1 verified" verified={wk1Verified} total={wk1Rows.length} />
          <StatusBadge label="Week 2 verified" verified={wk2Verified} total={wk2Rows.length} />
        </div>

        {!bothReady && (
          <div className="msg warning" style={{ marginBottom: 14, fontSize: 11 }}>
            ⚠ Both weeks must be fully verified before reconciliation can run.
            {wk1Rows.length === 0 && ' Week 1 has no verification data.'}
            {wk2Rows.length === 0 && ' Week 2 has no verification data.'}
          </div>
        )}

        {bothReady && !result && (
          <div className="msg success" style={{ marginBottom: 14, fontSize: 11 }}>
            ✓ Both weeks fully verified — ready to reconcile.
          </div>
        )}

        <button
          className="btn btn-primary"
          style={{ fontSize: 12, padding: '7px 20px', marginBottom: 14 }}
          disabled={!bothReady || running}
          onClick={handleReconcile}
        >
          {running ? '… Running reconciliation' : '▶ Run Reconciliation'}
        </button>

        {error && (
          <div className="msg error" style={{ marginBottom: 10, fontSize: 11 }}>✗ {error}</div>
        )}

        {result && (
          <div className="msg success" style={{ marginBottom: 14, fontSize: 11 }}>
            ✓ Reconciliation complete — {result.employee_count || 0} employees processed.
            Export nodes are now available.
          </div>
        )}

        <div style={{
          padding: '8px 12px', background: '#0d1117', borderRadius: 6,
          border: '1px solid #21262d', fontSize: 11, color: '#4b5563', lineHeight: 1.7,
        }}>
          <strong style={{ color: '#8b949e' }}>What reconciliation does:</strong>
          <ul style={{ margin: '6px 0 0 0', paddingLeft: 16 }}>
            <li>Combines Week 1 + Week 2 approved hours into biweekly totals</li>
            <li>Applies REG/OT/DBL classification across the full pay period</li>
            <li>Generates the payroll cheque run data for Sage 50</li>
            <li>Locks the period for export</li>
          </ul>
        </div>
      </div>
    </>
  )
}
