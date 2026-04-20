/**
 * InvoicePanel — weekly invoice preview for Sage 50 entry.
 *
 * Billable employees only (internal employees excluded).
 * Shows 6 standard line types per employee + individual expense lines.
 * Applies current billing rates and computes subtotal / HST / total.
 * Debug CSV button exports the full line-item breakdown.
 */
import { useState, useEffect, useCallback } from 'react'
import { getInvoicePreview } from '../api'
import { downloadCsv } from '../utils/csv'

function fmtC(n) {
  if (!n || n === 0) return ''
  return '$' + Number(n).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtQ(n) {
  if (!n || n === 0) return ''
  return Number(n).toFixed(1)
}

function buildInvoiceCsvRows(data) {
  const rows = [['Employee','Status','Item No.','Description','Qty','Unit Price','Amount']]
  for (const emp of data.employees) {
    for (const ln of emp.lines) {
      rows.push([emp.display_name,emp.status,ln.item_no,ln.description,ln.is_zero?'':ln.qty.toFixed(2),ln.unit_price.toFixed(2),ln.is_zero?'':ln.amount.toFixed(2)])
    }
    rows.push([emp.display_name,'','','Subtotal','','',emp.subtotal.toFixed(2)])
    rows.push([])
  }
  rows.push(['','','','Grand Subtotal','','',data.subtotal.toFixed(2)])
  rows.push(['','','',`HST ${(data.hst_rate*100).toFixed(0)}%`,'','',data.hst_amount.toFixed(2)])
  rows.push(['','','','Total','','',data.total.toFixed(2)])
  return rows
}

export default function InvoicePanel({ periodId, weekNum, onClose }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await getInvoicePreview(periodId, weekNum))
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setLoading(false)
    }
  }, [periodId, weekNum])

  useEffect(() => { if (periodId) load() }, [periodId, weekNum])

  return (
    <>
      <div className="panel-header">
        <h2>💰 Week {weekNum} — Invoice</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        {error && <div className="msg error" style={{ marginBottom: 10 }}>✗ {error}</div>}
        {loading && <div style={{ color: '#4b5563', fontSize: 12 }}>Loading…</div>}

        {!loading && data && (
          <>
            {/* Status bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              {data.all_verified
                ? <span className="msg success" style={{ marginBottom: 0, fontSize: 11 }}>
                    ✓ All billable employees verified — ready for Sage 50 entry
                  </span>
                : <span className="msg warning" style={{ marginBottom: 0, fontSize: 11 }}>
                    ⚠ Some employees not yet verified — invoice is a preview only
                  </span>
              }
              {data.employees.length > 0 && (
                <button
                  className="btn btn-ghost"
                  style={{ marginLeft: 'auto', fontSize: 10, padding: '3px 10px', whiteSpace: 'nowrap' }}
                  onClick={() => downloadCsv(buildInvoiceCsvRows(data), `debug_invoice_wk${weekNum}.csv`)}
                >
                  ↓ Debug CSV
                </button>
              )}
            </div>

            {data.employees.length === 0 && (
              <div style={{ fontSize: 12, color: '#4b5563' }}>
                No billable employees verified for this week. Run verification in Compare first.
              </div>
            )}

            {/* Per-employee sections */}
            {data.employees.map(emp => (
              <div key={emp.employee_id} style={{ marginBottom: 18 }}>
                {/* Employee header */}
                <div style={{
                  fontSize: 11, fontWeight: 700, color: '#e2e8f0',
                  padding: '4px 0 6px 0',
                  borderBottom: '1px solid #374151',
                  marginBottom: 4,
                  display: 'flex', alignItems: 'center', gap: 8,
                }}>
                  <span>*** {emp.display_name}</span>
                  {emp.status !== 'verified' && (
                    <span style={{
                      fontSize: 9, color: emp.status === 'needs_review' ? '#f59e0b' : '#4b5563',
                      fontWeight: 400,
                    }}>
                      ({emp.status})
                    </span>
                  )}
                  <span style={{ marginLeft: 'auto', color: '#4b5563', fontWeight: 400 }}>
                    {emp.subtotal > 0 ? fmtC(emp.subtotal) : ''}
                  </span>
                </div>

                {/* Line items */}
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <colgroup>
                    <col style={{ width: 115 }} />
                    <col style={{ width: 40 }} />
                    <col style={{ width: 45 }} />
                    <col />
                    <col style={{ width: 20 }} />
                    <col style={{ width: 60 }} />
                    <col style={{ width: 70 }} />
                  </colgroup>
                  <tbody>
                    {emp.lines.map((ln, i) => (
                      <tr key={i} style={{
                        color: ln.is_zero ? '#374151' : '#c9d1d9',
                        borderBottom: '1px solid #161b22',
                      }}>
                        <td style={{ padding: '3px 6px 3px 0', fontFamily: 'monospace', fontSize: 10 }}>
                          {ln.item_no}
                        </td>
                        <td style={{ padding: '3px 4px', color: '#4b5563', fontSize: 10 }}>Each</td>
                        <td style={{ padding: '3px 4px', textAlign: 'right', color: ln.is_zero ? '#374151' : '#58a6ff' }}>
                          {fmtQ(ln.qty)}
                        </td>
                        <td style={{ padding: '3px 6px' }}>{ln.description}</td>
                        <td style={{ padding: '3px 4px', textAlign: 'center', color: '#4b5563', fontSize: 10 }}>H</td>
                        <td style={{ padding: '3px 4px', textAlign: 'right', color: '#8b949e' }}>
                          {ln.unit_price.toFixed(2)}
                        </td>
                        <td style={{ padding: '3px 0 3px 8px', textAlign: 'right', fontWeight: ln.amount > 0 ? 600 : 400, color: ln.amount > 0 ? '#e2e8f0' : '#374151' }}>
                          {ln.amount > 0 ? fmtC(ln.amount) : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}

            {/* Invoice totals */}
            {data.employees.length > 0 && (
              <div style={{
                marginTop: 8, borderTop: '1px solid #374151', paddingTop: 10,
              }}>
                <table style={{ marginLeft: 'auto', borderCollapse: 'collapse', fontSize: 12 }}>
                  <tbody>
                    <tr>
                      <td style={{ padding: '3px 24px 3px 0', color: '#8b949e' }}>Subtotal:</td>
                      <td style={{ padding: '3px 0', textAlign: 'right', color: '#e2e8f0', fontWeight: 600 }}>
                        {fmtC(data.subtotal)}
                      </td>
                    </tr>
                    <tr>
                      <td style={{ padding: '3px 24px 3px 0', color: '#8b949e' }}>
                        H – HST {(data.hst_rate * 100).toFixed(0)}%
                      </td>
                      <td style={{ padding: '3px 0', textAlign: 'right', color: '#e2e8f0' }}>
                        {fmtC(data.hst_amount)}
                      </td>
                    </tr>
                    <tr style={{ borderTop: '1px solid #374151' }}>
                      <td style={{ padding: '6px 24px 3px 0', color: '#e2e8f0', fontWeight: 700 }}>
                        Total Amount
                      </td>
                      <td style={{ padding: '6px 0 3px', textAlign: 'right', color: '#22c55e', fontWeight: 700, fontSize: 14 }}>
                        {fmtC(data.total)}
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div style={{ fontSize: 10, color: '#4b5563', marginTop: 10, lineHeight: 1.6 }}>
                  Rates: REG $72.00 · OT1 $93.60 · OT2 $122.40 · Travel $72.00 · Per Diem $70.00/day · HST 13%
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
