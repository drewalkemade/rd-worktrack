/**
 * VerifyPanel — final per-employee sign-off for a week.
 *
 * Shows every employee's approved hours (REG/OT/DBL/Travel) alongside their
 * timesheet totals.  The owner verifies each employee when satisfied that the
 * numbers are correct.  Employees with unresolved variances are blocked until
 * the Resolve node is complete.
 *
 * Verified hours feed into the Invoice node.  All employees must be verified
 * before the week can be exported.
 */
import { useState, useEffect, useCallback } from 'react'
import { getVerification, runVerification, setVerified } from '../api'
import { downloadCsv } from '../utils/csv'
// runVerification is called silently on load — no manual trigger needed

function fmtH(n) {
  if (!n || n === 0) return '—'
  return Number(n).toFixed(2)
}

function fmtDt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ── Single employee card ──────────────────────────────────────────────────────

function EmployeeCard({ row, periodId, weekNum, onRefresh }) {
  const [saving, setSaving]   = useState(false)
  const [error,  setError]    = useState(null)

  const handleVerify = async () => {
    setSaving(true)
    setError(null)
    try {
      await setVerified(periodId, weekNum, row.employee_id, null)
      onRefresh()
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      setError(typeof detail === 'object' ? JSON.stringify(detail) : String(detail))
    } finally {
      setSaving(false)
    }
  }

  const isVerified    = row.status === 'verified'
  const needsReview   = row.status === 'needs_review'
  const hasVariance   = Math.abs(row.reg_variance) >= 0.01 ||
                        Math.abs(row.ot_variance)  >= 0.01 ||
                        Math.abs(row.dbl_variance) >= 0.01

  const borderColor = isVerified  ? '#166534'
                    : needsReview ? '#92400e'
                    : '#21262d'
  const bgColor     = isVerified  ? 'rgba(34,197,94,0.04)'
                    : needsReview ? 'rgba(245,158,11,0.04)'
                    : 'transparent'

  return (
    <div style={{
      border: `1px solid ${borderColor}`,
      borderRadius: 8,
      padding: '12px 16px',
      marginBottom: 10,
      background: bgColor,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#e2e8f0', flex: 1 }}>
          {isVerified && <span style={{ color: '#22c55e', marginRight: 6 }}>✓</span>}
          {row.display_name}
        </span>

        {isVerified && (
          <span style={{ fontSize: 10, color: '#22c55e' }}>
            Verified {fmtDt(row.verified_at)}
          </span>
        )}
        {needsReview && (
          <span style={{
            fontSize: 10, color: '#f59e0b',
            background: 'rgba(245,158,11,0.1)', borderRadius: 4,
            padding: '2px 7px',
          }}>
            ⚠ Variance
          </span>
        )}
        {!isVerified && (
          <button
            className="btn btn-primary"
            style={{ padding: '4px 14px', fontSize: 11 }}
            disabled={saving}
            onClick={handleVerify}
          >
            {saving ? '…' : '✓ Verify'}
          </button>
        )}
      </div>

      {/* Hours grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr) auto',
        gap: '0 12px',
        fontSize: 11,
      }}>
        {/* Approved row */}
        <div style={{ color: '#4b5563', fontSize: 10, gridColumn: '1 / -1', marginBottom: 2 }}>
          Approved (billing)
        </div>
        <HoursCell label="REG" value={row.approved_reg}  color="#58a6ff" />
        <HoursCell label="OT"  value={row.approved_ot}   color="#a78bfa" />
        <HoursCell label="DBL" value={row.approved_dbl}  color="#f59e0b" />
        <HoursCell label="Travel" value={row.approved_travel} color="#8b949e" italic />
        <div />

        {/* Variance row — only if there is one */}
        {hasVariance && (
          <>
            <div style={{ color: '#4b5563', fontSize: 10, gridColumn: '1 / -1', marginTop: 6, marginBottom: 2 }}>
              Variance (approved − timesheet)
            </div>
            <VarianceCell label="REG" value={row.reg_variance} />
            <VarianceCell label="OT"  value={row.ot_variance}  />
            <VarianceCell label="DBL" value={row.dbl_variance} />
            <div />
            <div />
          </>
        )}

        {/* Timesheet extras row */}
        {(row.timesheet_sick > 0 || row.timesheet_vacation > 0 ||
          row.timesheet_holiday > 0 || row.timesheet_nonbill > 0) && (
          <>
            <div style={{ color: '#4b5563', fontSize: 10, gridColumn: '1 / -1', marginTop: 6, marginBottom: 2 }}>
              Timesheet extras
            </div>
            {row.timesheet_sick     > 0 && <HoursCell label="Sick"     value={row.timesheet_sick}     color="#6b7280" />}
            {row.timesheet_vacation > 0 && <HoursCell label="Vacation" value={row.timesheet_vacation} color="#6b7280" />}
            {row.timesheet_holiday  > 0 && <HoursCell label="Holiday"  value={row.timesheet_holiday}  color="#6b7280" />}
            {row.timesheet_nonbill  > 0 && <HoursCell label="Non-bill" value={row.timesheet_nonbill}  color="#6b7280" />}
          </>
        )}
      </div>

      {/* Expense note */}
      {row.needs_expense_review && (
        <div style={{
          marginTop: 8, fontSize: 10, color: '#f59e0b',
          background: 'rgba(245,158,11,0.07)', borderRadius: 4,
          padding: '3px 8px',
        }}>
          💰 Expense review flagged
          {row.extra_expense_note && <span style={{ color: '#8b949e', marginLeft: 6 }}>— {row.extra_expense_note}</span>}
        </div>
      )}

      {error && (
        <div className="msg error" style={{ marginTop: 6, fontSize: 10 }}>✗ {error}</div>
      )}
    </div>
  )
}

function HoursCell({ label, value, color, italic }) {
  return (
    <div>
      <div style={{ color: '#4b5563', fontSize: 9, marginBottom: 1 }}>{label}</div>
      <div style={{ color, fontWeight: 600, fontSize: 12, fontStyle: italic ? 'italic' : 'normal' }}>
        {fmtH(value)}
      </div>
    </div>
  )
}

function VarianceCell({ label, value }) {
  if (Math.abs(value) < 0.01) return <div />
  const color = value > 0 ? '#ef4444' : '#f59e0b'
  const sign  = value > 0 ? '−' : '+'
  return (
    <div>
      <div style={{ color: '#4b5563', fontSize: 9, marginBottom: 1 }}>{label}</div>
      <div style={{ color, fontWeight: 700, fontSize: 12 }}>
        {sign}{Math.abs(value).toFixed(2)}
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function VerifyPanel({ periodId, weekNum, onClose, onDone }) {
  const [verification, setVerification] = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [verifyingAll, setVerifyingAll] = useState(false)
  const [error,        setError]        = useState(null)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      // Re-run silently on every load so correction decisions are reflected
      // without the owner needing to click anything. Verified rows are never
      // downgraded by the verifier.
      await runVerification(periodId, weekNum)
      const v = await getVerification(periodId, weekNum)
      setVerification(v)
      onDone?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [periodId, weekNum])

  useEffect(() => {
    if (periodId) loadAll()
  }, [periodId, weekNum])

  const handleVerifyAll = async () => {
    const readyRows = (verification?.rows || []).filter(r => r.status === 'pending' || r.status === 'needs_review')
    if (!readyRows.length) return
    setVerifyingAll(true)
    setError(null)
    try {
      await Promise.all(readyRows.map(r => setVerified(periodId, weekNum, r.employee_id, null)))
      await loadAll()
      onDone?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setVerifyingAll(false)
    }
  }

  const rows         = verification?.rows || []
  const verifiedRows = rows.filter(r => r.status === 'verified')
  const pendingRows  = rows.filter(r => r.status === 'pending')
  const reviewRows   = rows.filter(r => r.status === 'needs_review')
  const allVerified  = rows.length > 0 && rows.every(r => r.status === 'verified')

  return (
    <>
      <div className="panel-header">
        <h2>✅ Week {weekNum} — Verify</h2>
        {rows.length > 0 && (
          <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => {
              const out = [['Employee','Status','Approved REG','Approved OT','Approved DBL','Approved Travel','TS REG','TS OT1','TS OT2','TS Drive','Per Diem Days','Needs Expense Review']]
              for (const r of rows) {
                out.push([r.display_name,r.status,r.approved_reg,r.approved_ot,r.approved_dbl,r.approved_travel,r.timesheet_reg,r.timesheet_ot1,r.timesheet_ot2,r.timesheet_drive,r.simple_per_diem_count,r.needs_expense_review?1:0])
              }
              downloadCsv(out, `debug_verify_wk${weekNum}.csv`)
            }}>↓ Debug CSV</button>
        )}
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 14, lineHeight: 1.6 }}>
          Final sign-off per employee. Approved hours shown here feed into the Invoice node.
          All employees must be verified before export is available.
        </div>

        {loading && (
          <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 14 }}>Checking status…</div>
        )}
        {!loading && rows.length > 0 && (
          <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 14 }}>
            {verifiedRows.length} / {rows.length} verified
            {reviewRows.length > 0 && (
              <span style={{ color: '#f59e0b', marginLeft: 8 }}>
                · {reviewRows.length} with hour variances
              </span>
            )}
          </div>
        )}

        {error && (
          <div className="msg error" style={{ marginBottom: 10, fontSize: 11 }}>✗ {error}</div>
        )}

        {!rows.length && (
          <div style={{ fontSize: 12, color: '#4b5563' }}>
            No verification data — run verification first.
          </div>
        )}

        {allVerified && (
          <div className="msg success" style={{ marginBottom: 14, fontSize: 11 }}>
            ✓ All employees verified. This week is ready for the Invoice node.
          </div>
        )}

        {/* needs_review + pending — all ready to verify */}
        {(reviewRows.length > 0 || pendingRows.length > 0) && (
          <div style={{ marginBottom: 8 }}>
            {(reviewRows.length + pendingRows.length) > 1 && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <div style={{ fontSize: 10, color: '#8b949e', fontWeight: 600 }}>
                  READY TO VERIFY
                  {reviewRows.length > 0 && (
                    <span style={{ color: '#f59e0b', marginLeft: 8, fontWeight: 400 }}>
                      · {reviewRows.length} with variances
                    </span>
                  )}
                </div>
                <button
                  className="btn btn-primary"
                  style={{ fontSize: 11, padding: '3px 12px' }}
                  disabled={verifyingAll}
                  onClick={handleVerifyAll}
                >
                  {verifyingAll ? '…' : `✓ Verify All (${reviewRows.length + pendingRows.length})`}
                </button>
              </div>
            )}
            {reviewRows.map(r => (
              <EmployeeCard
                key={r.employee_id}
                row={r}
                periodId={periodId}
                weekNum={weekNum}
                onRefresh={loadAll}
              />
            ))}
            {pendingRows.map(r => (
              <EmployeeCard
                key={r.employee_id}
                row={r}
                periodId={periodId}
                weekNum={weekNum}
                onRefresh={loadAll}
              />
            ))}
          </div>
        )}

        {/* verified — done */}
        {verifiedRows.length > 0 && (
          <div>
            {!allVerified && (
              <div style={{ fontSize: 10, color: '#22c55e', marginBottom: 6, fontWeight: 600 }}>
                VERIFIED
              </div>
            )}
            {verifiedRows.map(r => (
              <EmployeeCard
                key={r.employee_id}
                row={r}
                periodId={periodId}
                weekNum={weekNum}
                onRefresh={loadAll}
              />
            ))}
          </div>
        )}

        {rows.length > 0 && !allVerified && reviewRows.length > 0 && (
          <div style={{
            marginTop: 12, padding: '8px 12px',
            background: '#0d1117', borderRadius: 6,
            border: '1px solid #21262d', fontSize: 11, color: '#4b5563',
            lineHeight: 1.7,
          }}>
            <strong style={{ color: '#8b949e' }}>⚠ Variance note:</strong> Some employees have
            hour variances between approved and timesheet. Use the{' '}
            <strong style={{ color: '#8b949e' }}>Resolve</strong> node to adjudicate each day,
            or verify anyway if you have already reviewed and accepted the difference.
          </div>
        )}

      </div>
    </>
  )
}
