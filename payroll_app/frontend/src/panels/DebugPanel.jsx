/**
 * DebugPanel.jsx — Developer / debug tools.
 *
 * Accessible from the topbar debug button.  Provides:
 *   - DB table row-count overview
 *   - Clear imported data (keeps employees)
 *   - Full clear + reseed (wipes everything, re-seeds from defaults)
 */
import { useState, useEffect } from 'react'
import { debugStats, debugClearImportedData, debugClearAndReseed } from '../api'

// Tables shown in the stats grid, grouped visually.
const STAT_GROUPS = [
  {
    label: 'Employees',
    tables: ['employees', 'employee_aliases', 'employee_rates', 'employee_assignments'],
  },
  {
    label: 'Periods & Approvals',
    tables: ['pay_periods', 'weekly_approvals', 'source_files'],
  },
  {
    label: 'Hours',
    tables: [
      'customer_hours', 'travel_hours', 'customer_daily_hours',
      'timesheet_imports', 'timesheet_hours', 'timesheet_daily_hours',
      'weekly_employee_verification',
    ],
  },
  {
    label: 'Expenses & Reconciliation',
    tables: ['expense_items', 'expense_receipts', 'reconciliation'],
  },
  {
    label: 'Audit',
    tables: ['audit_log', 'source_file_edits'],
  },
]

export default function DebugPanel({ onClose, onReset }) {
  const [stats,   setStats]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [msg,     setMsg]     = useState(null)   // { text, ok }

  const loadStats = () => {
    setLoading(true)
    debugStats()
      .then(d => setStats(d.tables))
      .catch(() => setMsg({ text: 'Failed to load stats', ok: false }))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadStats() }, [])

  const clearMsg = () => setMsg(null)

  const handleClearImported = async () => {
    if (!window.confirm(
      'Clear all imported data?\n\nPay periods, approvals, hours, expenses, source files, and audit log will be deleted.\nEmployees and aliases are preserved.'
    )) return

    setLoading(true)
    clearMsg()
    try {
      await debugClearImportedData()
      setMsg({ text: 'Imported data cleared. Employees preserved.', ok: true })
      loadStats()
      onReset?.()
    } catch {
      setMsg({ text: 'Clear failed — check the backend console.', ok: false })
    } finally {
      setLoading(false)
    }
  }

  const handleClearReseed = async () => {
    const typed = window.prompt(
      'This will delete EVERYTHING including employees, then re-seed from defaults.\n\nType RESET to confirm:'
    )
    if (typed !== 'RESET') {
      setMsg({ text: 'Cancelled — you must type RESET exactly.', ok: false })
      return
    }

    setLoading(true)
    clearMsg()
    try {
      await debugClearAndReseed()
      setMsg({ text: 'Database cleared and re-seeded with default employees.', ok: true })
      loadStats()
      onReset?.()
    } catch {
      setMsg({ text: 'Reset failed — check the backend console.', ok: false })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="panel-header" style={{ background: '#2d1a0e', borderBottom: '1px solid #7c4a1e' }}>
        <h2 style={{ color: '#fb923c' }}>🛠 Debug Tools</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body" style={{ padding: '16px 20px' }}>

        {/* ── Message banner ─────────────────────────────────────────────── */}
        {msg && (
          <div style={{
            marginBottom: 16,
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: 13,
            background: msg.ok ? '#14532d' : '#450a0a',
            color:      msg.ok ? '#86efac' : '#fca5a5',
            border:     `1px solid ${msg.ok ? '#166534' : '#7f1d1d'}`,
          }}>
            {msg.text}
          </div>
        )}

        {/* ── Actions ────────────────────────────────────────────────────── */}
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ color: '#94a3b8', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, margin: '0 0 10px' }}>
            Actions
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button
              onClick={handleClearImported}
              disabled={loading}
              style={btnStyle('#92400e', '#fbbf24')}
            >
              Clear Imported Data
              <span style={{ fontSize: 11, opacity: 0.7, marginLeft: 8 }}>(keeps employees)</span>
            </button>

            <button
              onClick={handleClearReseed}
              disabled={loading}
              style={btnStyle('#7f1d1d', '#f87171')}
            >
              Clear Everything + Reseed
              <span style={{ fontSize: 11, opacity: 0.7, marginLeft: 8 }}>(wipes employees too)</span>
            </button>

            <button
              onClick={loadStats}
              disabled={loading}
              style={btnStyle('#1e3a5f', '#93c5fd')}
            >
              Refresh Stats
            </button>
          </div>
        </section>

        {/* ── DB stats ───────────────────────────────────────────────────── */}
        <section>
          <h3 style={{ color: '#94a3b8', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, margin: '0 0 10px' }}>
            Database Row Counts
          </h3>

          {loading && !stats && (
            <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
          )}

          {stats && STAT_GROUPS.map(group => (
            <div key={group.label} style={{ marginBottom: 14 }}>
              <div style={{ color: '#64748b', fontSize: 11, marginBottom: 4 }}>{group.label}</div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <tbody>
                  {group.tables.map(table => (
                    <tr key={table}>
                      <td style={tdStyle('left')}>{table}</td>
                      <td style={{ ...tdStyle('right'), color: stats[table] > 0 ? '#e2e8f0' : '#4b5563', fontVariantNumeric: 'tabular-nums' }}>
                        {stats[table] ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>

      </div>
    </>
  )
}

function btnStyle(bg, fg) {
  return {
    background: bg,
    color: fg,
    border: `1px solid ${fg}33`,
    borderRadius: 6,
    padding: '8px 14px',
    fontSize: 13,
    cursor: 'pointer',
    textAlign: 'left',
    width: '100%',
  }
}

function tdStyle(align) {
  return {
    padding: '3px 6px',
    fontSize: 12,
    color: '#8b949e',
    textAlign: align,
    borderBottom: '1px solid #1e293b',
  }
}
